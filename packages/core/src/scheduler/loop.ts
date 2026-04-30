import type { Aria2Client } from "../aria2/client.js";
import { pauseAll } from "../aria2/methods.js";
import type { ActionLog } from "../storage/action-log.js";
import type { DeclarationStore } from "../storage/declaration.js";
import type { QueueStore } from "../storage/queue.js";
import type { StateStore } from "../storage/state.js";
import { runSchedulerTick, type SchedulerTickResult } from "./tick.js";
import { pollActiveItems, type PollResult } from "./poll.js";
import { runRetryPass, type RetryResult } from "./retry.js";
import { TERMINAL_STATUSES, type ItemStatus } from "../queue/types.js";

export interface SchedulerLoopDeps {
  queueStore: QueueStore;
  stateStore: StateStore;
  declarationStore: DeclarationStore;
  actionLog: ActionLog;
  aria2: Aria2Client;
}

export interface SchedulerLoopOptions {
  /** Cap fed to dispatchDownload on each tick (resolved by the caller). */
  capBytesPerSec?: number;
  /** Sleep between iterations, ms. Default 2000. */
  intervalMs?: number;
  /** Maximum iterations to run before returning (testing/short runs). */
  maxIterations?: number;
  /** Abort signal for graceful shutdown. */
  signal?: AbortSignal;
  /** Optional per-iteration callback (testing / live progress). */
  onIteration?: (iteration: number, result: SchedulerLoopIteration) => void | Promise<void>;
  /**
   * One-shot work to run before the polling loop starts. Receives the
   * deps and returns an updated capBytesPerSec (e.g. derived from a
   * fresh bandwidth probe). Errors are swallowed and a "scheduler_pre"
   * action is recorded with outcome="failed".
   */
  preLoop?: (deps: SchedulerLoopDeps) => Promise<{ capBytesPerSec?: number } | void>;
}

export interface SchedulerLoopIteration {
  tick: SchedulerTickResult;
  poll: PollResult;
  retry: RetryResult;
  /** True when state.paused was set on this iteration (the tick was skipped). */
  paused: boolean;
  /** Live count of non-terminal rows after the iteration. */
  in_flight: number;
}

const sleep = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    if (signal?.aborted) return resolve();
    const timer = setTimeout(resolve, ms);
    timer.unref?.();
    if (signal) {
      const onAbort = () => {
        clearTimeout(timer);
        resolve();
      };
      signal.addEventListener("abort", onAbort, { once: true });
    }
  });

const isTerminal = (status: unknown): boolean =>
  TERMINAL_STATUSES.has(String(status ?? "") as ItemStatus);

/**
 * Long-running scheduler driver. Each iteration:
 *   1. Set state.running=true.
 *   2. If state.paused, skip the tick but still poll for transitions.
 *   3. runSchedulerTick() — dispatch any queued items up to cap.
 *   4. pollActiveItems() — refresh live progress + transition completes/errors.
 *   5. Sleep intervalMs (interruptible by signal).
 *
 * Exits when:
 *   - signal aborts (graceful), or
 *   - maxIterations is reached, or
 *   - in_flight hits 0 AND no queued items remain (drained).
 *
 * On exit, sets state.running=false and (if abort was requested) records
 * a "scheduler_stopped" action so /api/log shows the shutdown.
 *
 * Mirrors the polling structure of scheduler.process_queue. The
 * bandwidth-probe / reconcile / dedup composition is deferred to a
 * higher-level "ariaflow start" command that runs them once before
 * handing off to runSchedulerLoop.
 */
export async function runSchedulerLoop(
  deps: SchedulerLoopDeps,
  opts: SchedulerLoopOptions = {},
): Promise<{ iterations: number; reason: "drained" | "max_iterations" | "aborted" }> {
  const intervalMs = opts.intervalMs ?? 2000;
  let cap = opts.capBytesPerSec ?? 0;

  await deps.stateStore.update((s) => {
    s.running = true;
  });

  if (opts.preLoop) {
    try {
      const out = await opts.preLoop(deps);
      if (out && typeof out.capBytesPerSec === "number") cap = out.capBytesPerSec;
    } catch (err) {
      await deps.actionLog.record({
        action: "scheduler_pre",
        target: "scheduler",
        outcome: "failed",
        reason: "preloop_error",
        detail: { error: err instanceof Error ? err.message : String(err) },
      });
    }
  }

  let iterations = 0;
  let reason: "drained" | "max_iterations" | "aborted" = "drained";

  try {
    while (!opts.signal?.aborted) {
      const state = await deps.stateStore.load();
      const paused = Boolean(state.paused);
      let tick: SchedulerTickResult = { started: [], failed: [], saturated: false };
      if (!paused) {
        tick = await runSchedulerTick({
          queueStore: deps.queueStore,
          declarationStore: deps.declarationStore,
          actionLog: deps.actionLog,
          aria2: deps.aria2,
          capBytesPerSec: cap,
        });
      }
      const poll = await pollActiveItems({
        queueStore: deps.queueStore,
        actionLog: deps.actionLog,
        aria2: deps.aria2,
      });

      // Re-arm retries: any items that just landed in "error" via the
      // poll pass (or were already errored from a prior run) get
      // rescheduled here, so the next tick can pick them up once their
      // backoff expires.
      const retry = await runRetryPass({
        queueStore: deps.queueStore,
        declarationStore: deps.declarationStore,
        actionLog: deps.actionLog,
      });

      const items = await deps.queueStore.load();
      const inFlight = items.filter((i) => !isTerminal(i.status)).length;
      iterations += 1;
      const iteration: SchedulerLoopIteration = {
        tick,
        poll,
        retry,
        paused,
        in_flight: inFlight,
      };
      if (opts.onIteration) await opts.onIteration(iterations, iteration);

      if (opts.maxIterations && iterations >= opts.maxIterations) {
        reason = "max_iterations";
        break;
      }
      // Drained: nothing in flight, nothing waiting. Don't loop forever.
      if (inFlight === 0) {
        const queuedRemaining = items.some((i) => i.status === "queued");
        if (!queuedRemaining) {
          reason = "drained";
          break;
        }
      }

      await sleep(intervalMs, opts.signal);
    }
    if (opts.signal?.aborted) reason = "aborted";
  } finally {
    // ASM CR-3: leaving the run-state means no jobs may stay in the
    // active tier on aria2's side. Best-effort pauseAll before flipping
    // running=false; aria2 may already be unreachable on a crash, so
    // swallow the error and write the state regardless.
    try {
      await pauseAll(deps.aria2);
    } catch {
      /* daemon unreachable — proceed with state update anyway */
    }
    await deps.stateStore.update((s) => {
      s.running = false;
      s.active_gid = null;
      s.active_url = null;
    });
    if (reason === "aborted") {
      await deps.actionLog.record({
        action: "scheduler_stopped",
        target: "scheduler",
        outcome: "changed",
        reason: "abort_signal",
        detail: { iterations },
      });
    }
  }

  return { iterations, reason };
}
