import type { StateStore } from "../storage/state.js";

export interface StartResult {
  started: boolean;
  reason: string;
}
export interface StopResult {
  stopped: boolean;
  reason: string;
}

/**
 * BG-40: invoke the scheduler `start` dep with operator-intent
 * bookkeeping. Stamps `state.scheduler_intent = "running"` first so
 * the bootstrap window reports "starting" (not "stopped"); rolls
 * intent back to "stopped" on a genuine failure. `already_running`
 * is preserved as "running" — the loop IS up, intent is correct.
 *
 * Catches throws from the inner fn so callers (e.g. /api/downloads
 * auto-kick) don't have to write the same try/catch.
 */
export async function callStartScheduler(
  stateStore: StateStore,
  start: () => Promise<StartResult>,
): Promise<StartResult> {
  await stateStore.update((s) => {
    s.scheduler_intent = "running";
  });
  let result: StartResult;
  try {
    result = await start();
  } catch (err) {
    result = {
      started: false,
      reason: err instanceof Error ? err.message : "start_failed",
    };
  }
  if (!result.started && result.reason !== "already_running") {
    await stateStore.update((s) => {
      s.scheduler_intent = "stopped";
    });
  }
  return result;
}

/**
 * BG-40: invoke the scheduler `stop` dep with operator-intent
 * bookkeeping. Stamps `intent = "stopped"` regardless of whether the
 * loop was actually running — the operator's intent is recorded the
 * moment they hit /stop.
 */
export async function callStopScheduler(
  stateStore: StateStore,
  stop: () => Promise<StopResult>,
): Promise<StopResult> {
  await stateStore.update((s) => {
    s.scheduler_intent = "stopped";
  });
  return stop();
}
