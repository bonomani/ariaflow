import type { Aria2Client } from "../aria2/client.js";
import type { ActionLog } from "../storage/action-log.js";
import type { DeclarationStore } from "../storage/declaration.js";
import type { QueueStore } from "../storage/queue.js";
import type { StateStore } from "../storage/state.js";
import { runSchedulerTick, type SchedulerTickResult } from "./tick.js";
import { pollActiveItems, type PollResult } from "./poll.js";
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
}

export interface SchedulerLoopIteration {
  tick: SchedulerTickResult;
  poll: PollResult;
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
  const cap = opts.capBytesPerSec ?? 0;

  await deps.stateStore.update((s) => {
    s.running = true;
  });

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

      const items = await deps.queueStore.load();
      const inFlight = items.filter((i) => !isTerminal(i.status)).length;
      iterations += 1;
      const iteration: SchedulerLoopIteration = {
        tick,
        poll,
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
    await deps.stateStore.update((s) => {
      s.running = false;
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
