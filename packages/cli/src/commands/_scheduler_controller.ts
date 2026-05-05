import {
  Aria2Client,
  bandwidthConfigFrom,
  deduplicateActiveTransfers,
  reconcileLiveQueue,
  runBandwidthProbe,
  runSchedulerLoop,
} from "@ariaflow/core";
import type { CliContext } from "../context.js";

export interface SchedulerControllerOptions {
  intervalMs?: number;
}

export interface SchedulerController {
  /** True iff a loop is currently running. */
  running: () => boolean;
  /** Idempotent: if a loop is already up, returns started=false / reason="already_running". */
  launch: () => Promise<{ started: boolean; reason: string }>;
  /** Idempotent: if no loop is up, returns stopped=false / reason="not_running". */
  stop: () => Promise<{ stopped: boolean; reason: string }>;
  /** Wait for the current loop (if any) to drain. Resolves immediately when nothing's running. */
  awaitDrain: () => Promise<unknown>;
}

/**
 * Build the scheduler controller used by `cmdServe`. Owns the abort
 * controller + done-promise that govern the long-running loop.
 *
 * Factored out of cmdServe so the lifecycle is independently testable
 * and the cmdServe body stays focused on HTTP/mDNS wiring.
 */
export function createSchedulerController(
  ctx: CliContext,
  aria2: Aria2Client | undefined,
  opts: SchedulerControllerOptions = {},
): SchedulerController {
  let ctrl: AbortController | undefined;
  let done: Promise<unknown> = Promise.resolve();

  const launch = async (): Promise<{ started: boolean; reason: string }> => {
    if (!aria2) return { started: false, reason: "aria2_unavailable" };
    if (ctrl && !ctrl.signal.aborted) {
      return { started: false, reason: "already_running" };
    }
    ctrl = new AbortController();
    const state = await ctx.state.load();
    const initialCap = Number(state.last_bandwidth_probe?.cap_bytes_per_sec ?? 0) || 0;
    done = runSchedulerLoop(
      {
        queueStore: ctx.queue,
        stateStore: ctx.state,
        declarationStore: ctx.declaration,
        actionLog: ctx.actions,
        aria2,
      },
      {
        capBytesPerSec: initialCap,
        intervalMs: opts.intervalMs ?? 2000,
        signal: ctrl.signal,
        preLoop: async () => {
          // Adopt orphan GIDs from a previous run before the loop
          // starts pushing new ones. Composes Phase 8's matcher to
          // avoid double-dispatching items aria2 is already running.
          await reconcileLiveQueue(
            {
              queueStore: ctx.queue,
              stateStore: ctx.state,
              actionLog: ctx.actions,
              aria2,
            },
            { adoptMissing: true },
          );
          // Drop duplicate active transfers so the scheduler doesn't
          // double-bill bandwidth to the same URL on startup.
          await deduplicateActiveTransfers({
            declarationStore: ctx.declaration,
            actionLog: ctx.actions,
            aria2,
          });
          // Refresh the bandwidth cap before entering the loop so the
          // first batch of dispatches respects the live network rate.
          const declaration = await ctx.declaration.load();
          const config = bandwidthConfigFrom(declaration);
          const fresh = await runBandwidthProbe({ config });
          await ctx.state.update((s) => {
            s.last_bandwidth_probe = fresh;
            s.last_bandwidth_probe_at = Date.now() / 1000;
          });
          await ctx.actions.record({
            action: "probe",
            target: "bandwidth",
            outcome: fresh.source === "networkquality" ? "changed" : "unchanged",
            reason: "scheduler_preloop",
            detail: fresh as unknown as Record<string, unknown>,
          });
          return { capBytesPerSec: fresh.cap_bytes_per_sec ?? 0 };
        },
      },
    ).then(
      () => {
        // Loop exited normally (drained / max_iterations) — clear the
        // controller so launch() can spin up a fresh loop when new
        // items arrive.
        ctrl = undefined;
        done = Promise.resolve();
      },
      (err) => {
        // Surface scheduler crashes to stderr but don't kill the HTTP
        // listener — caller can investigate via /api/log.
        console.error("scheduler loop crashed:", err);
        ctrl = undefined;
        done = Promise.resolve();
      },
    );
    // Wait one event-loop tick so the loop's first state.running=true
    // write lands before we report success — callers immediately read
    // /api/status after /start and would otherwise race the flip.
    await new Promise<void>((r) => setImmediate(r));
    return { started: true, reason: "started" };
  };

  const stop = async (): Promise<{ stopped: boolean; reason: string }> => {
    if (!ctrl || ctrl.signal.aborted) {
      return { stopped: false, reason: "not_running" };
    }
    ctrl.abort();
    await done;
    ctrl = undefined;
    done = Promise.resolve();
    return { stopped: true, reason: "stopped" };
  };

  return {
    running: () => Boolean(ctrl && !ctrl.signal.aborted),
    launch,
    stop,
    awaitDrain: () => done,
  };
}
