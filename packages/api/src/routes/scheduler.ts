import {
  ACTIONS,
  TARGETS,
  aria2,
  callStartScheduler,
  callStopScheduler,
  errorPayload,
  evaluatePreflight,
  probeAria2Reachable,
  summarizeQueue,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";
import { computeSchedulerStatus } from "./_scheduler_status.js";

export function registerSchedulerRoutes({ app, deps }: RouteContext): void {
  app.get("/api/scheduler", async () => {
    const s = await deps.stateStore.load();
    const { status, wait_reason } = await computeSchedulerStatus(deps, s);
    return withMeta("GET", "/api/scheduler", {
      status,
      wait_reason,
      running: Boolean(s.running),
      paused: Boolean(s.paused),
      session_id: s.session_id,
      session_started_at: s.session_started_at,
      session_closed_at: s.session_closed_at,
      _rev: Number(s._rev ?? 0),
    });
  });

  app.post("/api/scheduler/pause", async () => {
    const next = await deps.stateStore.update((s) => {
      s.paused = true;
    });
    // Operator semantic: pause = freeze everything, including in-flight
    // aria2 transfers (not just future dispatches). Best-effort: if the
    // daemon is unreachable, the state flip already happened so the
    // dispatch tier won't queue more, and the next /resume will also
    // try unpauseAll.
    let aria2Paused = false;
    if (deps.aria2) {
      try {
        await aria2.pauseAll(deps.aria2);
        aria2Paused = true;
      } catch {
        /* swallow — daemon unreachable */
      }
    }
    await deps.actionLog.record({
      action: ACTIONS.schedulerPause,
      target: TARGETS.scheduler,
      outcome: "changed",
      reason: "api_request",
      detail: { aria2_pause_all: aria2Paused },
    });
    return { ok: true, paused: next.paused, _rev: Number(next._rev ?? 0) };
  });

  // BG-48: /api/scheduler/contract is the operator-facing name.
  // /api/scheduler/ucc stays for one release of back-compat; both
  // call the same handler and both emit `action: "contract"` in the
  // audit log (see ACTIONS.schedulerContract → "contract").
  const runContract = async () => {
    const declaration = await deps.declarationStore.load();
    const aria2Available = (await probeAria2Reachable(deps.aria2)) === true;
    const stateBefore = await deps.stateStore.load();
    const queueBefore = await deps.queueStore.load();
    const pf = evaluatePreflight(declaration, {
      aria2_available: aria2Available,
      queue_readable: true,
      paused: stateBefore.paused,
    });
    if (pf.exit_code !== 0) {
      const result = {
        observation: "failed",
        outcome: "failed" as const,
        failure_class: "permanent",
        message: "preflight failed",
        reason: "gate_failed",
        observed_before: { gates: pf.gates },
        diff: { failures: pf.hard_failures },
      };
      await deps.actionLog.record({
        action: ACTIONS.schedulerContract,
        target: TARGETS.queue,
        outcome: result.outcome,
        observation: result.observation,
        reason: result.reason,
        before: { state: stateBefore, queue: summarizeQueue(queueBefore) },
        after: {
          state: await deps.stateStore.load(),
          queue: summarizeQueue(await deps.queueStore.load()),
          ucc: { result, preflight: pf },
        },
        detail: { result, preflight: pf },
      });
      return { meta: { contract: "UCC", version: "2.0" }, result, preflight: pf };
    }

    // Gates passed. The full process_queue() loop lives in the deferred
    // scheduler integration, so the UCC run currently converges on a
    // no-op with the live queue summary as the diff payload.
    const queueAfter = await deps.queueStore.load();
    const result = {
      observation: "ok",
      outcome: "converged" as const,
      message: "queue processed",
      reason: "converged",
      observed_before: { items: queueBefore },
      observed_after: { items: queueAfter },
      diff: {
        count_delta: queueAfter.length - queueBefore.length,
        summary: summarizeQueue(queueAfter),
        active: null,
      },
    };
    await deps.actionLog.record({
      action: ACTIONS.schedulerContract,
      target: TARGETS.queue,
      outcome: result.outcome,
      observation: result.observation,
      reason: result.reason,
      before: { state: stateBefore, queue: summarizeQueue(queueBefore) },
      after: {
        state: await deps.stateStore.load(),
        queue: summarizeQueue(queueAfter),
        ucc: { result, preflight: pf },
      },
      detail: { result, preflight: pf },
    });
    return { meta: { contract: "UCC", version: "2.0" }, result, preflight: pf };
  };

  app.post("/api/scheduler/contract", runContract);
  app.post("/api/scheduler/ucc", runContract);

  app.post("/api/scheduler/preflight", async () => {
    const declaration = await deps.declarationStore.load();
    const aria2Available = (await probeAria2Reachable(deps.aria2)) === true;
    const stateBefore = await deps.stateStore.load();
    const queueBefore = await deps.queueStore.load();
    const result = evaluatePreflight(declaration, {
      aria2_available: aria2Available,
      queue_readable: true,
      paused: stateBefore.paused,
    });
    await deps.actionLog.record({
      action: ACTIONS.schedulerPreflight,
      target: TARGETS.system,
      outcome: result.status === "pass" ? "converged" : "blocked",
      reason: result.status,
      before: { state: stateBefore, queue: summarizeQueue(queueBefore) },
      after: {
        state: await deps.stateStore.load(),
        queue: summarizeQueue(await deps.queueStore.load()),
        preflight: result as unknown as Record<string, unknown>,
      },
      detail: result as unknown as Record<string, unknown>,
    });
    return result;
  });

  app.post("/api/scheduler/resume", async () => {
    const next = await deps.stateStore.update((s) => {
      s.paused = false;
    });
    // Symmetric with /pause: unpause every aria2 transfer that /pause
    // froze. Best-effort — daemon may be unreachable.
    let aria2Unpaused = false;
    if (deps.aria2) {
      try {
        await aria2.unpauseAll(deps.aria2);
        aria2Unpaused = true;
      } catch {
        /* swallow — daemon unreachable */
      }
    }
    await deps.actionLog.record({
      action: ACTIONS.schedulerResume,
      target: TARGETS.scheduler,
      outcome: "changed",
      reason: "api_request",
      detail: { aria2_unpause_all: aria2Unpaused },
    });
    // BG-25: when the scheduler loop isn't running, /resume must also
    // start it — otherwise unpausing has no effect and queued items
    // sit forever. The dashboard's Start button hits /resume when
    // state.running=false, so this is the path that flips the loop on.
    // BG-40: callStartScheduler stamps the operator intent and rolls
    // it back on a genuine failure.
    let startResult: { started: boolean; reason: string } | undefined;
    const post = await deps.stateStore.load();
    if (!post.running && deps.startScheduler) {
      const start = deps.startScheduler;
      startResult = await callStartScheduler(deps.stateStore, () => start());
    }
    return {
      ok: true,
      paused: next.paused,
      _rev: Number(next._rev ?? 0),
      ...(startResult ? { started: startResult.started, start_reason: startResult.reason } : {}),
    };
  });

  // BG-25: explicit start/stop routes. `state.running` means "the
  // scheduler loop is actively dispatching" — both views agree on that
  // definition. /start is idempotent: if running is already true it
  // returns started:false / reason:"already_running" rather than
  // erroring.
  app.post("/api/scheduler/start", async (_req, reply) => {
    if (!deps.startScheduler) {
      return reply
        .code(503)
        .send(errorPayload("scheduler_unavailable", "scheduler lifecycle not wired"));
    }
    const before = await deps.stateStore.load();
    if (before.running) {
      return { ok: true, started: false, reason: "already_running", running: true };
    }
    const start = deps.startScheduler;
    const result = await callStartScheduler(deps.stateStore, () => start());
    const after = await deps.stateStore.load();
    await deps.actionLog.record({
      action: ACTIONS.schedulerStart,
      target: TARGETS.scheduler,
      outcome: result.started ? "changed" : "unchanged",
      reason: result.reason,
    });
    return {
      ok: true,
      started: result.started,
      reason: result.reason,
      running: Boolean(after.running),
      _rev: Number(after._rev ?? 0),
    };
  });

  app.post("/api/scheduler/stop", async (_req, reply) => {
    if (!deps.stopScheduler) {
      return reply
        .code(503)
        .send(errorPayload("scheduler_unavailable", "scheduler lifecycle not wired"));
    }
    const before = await deps.stateStore.load();
    const stop = deps.stopScheduler;
    // BG-40: callStopScheduler stamps intent="stopped" regardless of
    // whether the loop was actually running — the operator hit /stop
    // either way.
    if (!before.running) {
      await callStopScheduler(deps.stateStore, async () => ({
        stopped: false,
        reason: "not_running",
      }));
      return { ok: true, stopped: false, reason: "not_running", running: false };
    }
    const result = await callStopScheduler(deps.stateStore, () => stop());
    const after = await deps.stateStore.load();
    await deps.actionLog.record({
      action: ACTIONS.schedulerStop,
      target: TARGETS.scheduler,
      outcome: result.stopped ? "changed" : "unchanged",
      reason: result.reason,
    });
    return {
      ok: true,
      stopped: result.stopped,
      reason: result.reason,
      running: Boolean(after.running),
      _rev: Number(after._rev ?? 0),
    };
  });
}
