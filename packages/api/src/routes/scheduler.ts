import { errorPayload, evaluatePreflight, summarizeQueue } from "@ariaflow/core";
import type { RouteContext } from "./_context.js";

export function registerSchedulerRoutes({ app, deps }: RouteContext): void {
  app.get("/api/scheduler", async () => {
    const s = await deps.stateStore.load();
    const running = Boolean(s.running);
    const paused = Boolean(s.paused);
    const status = running && paused ? "paused" : running ? "running" : "starting";
    return {
      status,
      running,
      paused,
      session_id: s.session_id,
      session_started_at: s.session_started_at,
      session_closed_at: s.session_closed_at,
      _rev: Number(s._rev ?? 0),
    };
  });

  app.post("/api/scheduler/pause", async () => {
    const next = await deps.stateStore.update((s) => {
      s.paused = true;
    });
    await deps.actionLog.record({
      action: "pause",
      target: "scheduler",
      outcome: "changed",
      reason: "api_request",
    });
    return { ok: true, paused: next.paused, _rev: Number(next._rev ?? 0) };
  });

  app.post("/api/scheduler/ucc", async () => {
    const declaration = await deps.declarationStore.load();
    let aria2Available = false;
    if (deps.aria2) {
      try {
        await deps.aria2.call("aria2.getVersion");
        aria2Available = true;
      } catch {
        aria2Available = false;
      }
    }
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
        outcome: "failed",
        failure_class: "permanent",
        message: "preflight failed",
        reason: "gate_failed",
        observed_before: { gates: pf.gates },
        diff: { failures: pf.hard_failures },
      };
      await deps.actionLog.record({
        action: "ucc",
        target: "queue",
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
      outcome: "converged",
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
      action: "ucc",
      target: "queue",
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
  });

  app.post("/api/scheduler/preflight", async () => {
    const declaration = await deps.declarationStore.load();
    let aria2Available = false;
    if (deps.aria2) {
      try {
        await deps.aria2.call("aria2.getVersion");
        aria2Available = true;
      } catch {
        aria2Available = false;
      }
    }
    const stateBefore = await deps.stateStore.load();
    const queueBefore = await deps.queueStore.load();
    const result = evaluatePreflight(declaration, {
      aria2_available: aria2Available,
      queue_readable: true,
      paused: stateBefore.paused,
    });
    await deps.actionLog.record({
      action: "preflight",
      target: "system",
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
    await deps.actionLog.record({
      action: "resume",
      target: "scheduler",
      outcome: "changed",
      reason: "api_request",
    });
    // BG-25: when the scheduler loop isn't running, /resume must also
    // start it — otherwise unpausing has no effect and queued items sit
    // forever. The dashboard's Start button hits /resume when
    // state.running=false, so this is the path that has to flip the
    // loop on.
    let startResult: { started: boolean; reason: string } | undefined;
    const post = await deps.stateStore.load();
    if (!post.running && deps.startScheduler) {
      try {
        startResult = await deps.startScheduler();
      } catch (err) {
        startResult = {
          started: false,
          reason: err instanceof Error ? err.message : "start_failed",
        };
      }
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
    const result = await deps.startScheduler();
    const after = await deps.stateStore.load();
    await deps.actionLog.record({
      action: "start",
      target: "scheduler",
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
    if (!before.running) {
      return { ok: true, stopped: false, reason: "not_running", running: false };
    }
    const result = await deps.stopScheduler();
    const after = await deps.stateStore.load();
    await deps.actionLog.record({
      action: "stop",
      target: "scheduler",
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
