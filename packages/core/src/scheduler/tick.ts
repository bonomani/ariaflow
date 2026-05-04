import type { Aria2Client } from "../aria2/client.js";
import { dispatchDownload, dispatchPrefsFrom } from "../aria2/dispatch.js";
import type { ActionLog } from "../storage/action-log.js";
import type { DeclarationStore } from "../storage/declaration.js";
import type { QueueStore } from "../storage/queue.js";
import { maxSimultaneousDownloads } from "../transfers/helpers.js";
import { TERMINAL_STATUSES, type ItemStatus, type QueueItemRecord } from "../queue/types.js";
import { isRetryReady } from "./retry.js";

export interface SchedulerTickDeps {
  queueStore: QueueStore;
  declarationStore: DeclarationStore;
  actionLog: ActionLog;
  aria2: Aria2Client;
  /** Bytes/sec cap to apply on dispatch (passed straight to dispatchDownload). */
  capBytesPerSec: number;
  /**
   * BG-28(a): when supplied, the tick stamps state.active_gid /
   * active_url with the most recently dispatched item so the dashboard's
   * TRANSFER chip can spotlight it. Optional — pure tests can leave it
   * out and the active state stays untouched.
   */
  stateStore?: import("../storage/state.js").StateStore;
}

export interface SchedulerTickResult {
  /** Items started in this tick (gid assigned + status=active). */
  started: Array<{ id: string; gid: string }>;
  /** Item ids the tick attempted to start but the RPC threw on. */
  failed: Array<{ id: string; error: string }>;
  /** True if the tick noticed the concurrency cap is already saturated. */
  saturated: boolean;
}

const ACTIVE_STATUSES = new Set<ItemStatus>(["active", "waiting"]);

/**
 * Run one tick of the scheduler: pick the next queued items (in priority +
 * insertion order), respect max_simultaneous_downloads, dispatch each via
 * Aria2Client, and persist the resulting gid + status="active" back onto
 * the queue. Records a "start" action per dispatched item and a
 * "start_failed" action per RPC error.
 *
 * Pure of session / state / reconcile / bandwidth-probe concerns — the
 * caller composes those around the tick. This makes it cheap to test
 * with a mock Aria2Client and run it on demand from a CLI subcommand or
 * a long-running poller.
 */
export async function runSchedulerTick(deps: SchedulerTickDeps): Promise<SchedulerTickResult> {
  const declaration = await deps.declarationStore.load();
  const cap = maxSimultaneousDownloads(declaration);
  const items = await deps.queueStore.load();

  const activeCount = items.filter((i) =>
    ACTIVE_STATUSES.has(i.status as ItemStatus),
  ).length;
  if (cap > 0 && activeCount >= cap) {
    return { started: [], failed: [], saturated: true };
  }

  const now = Date.now();
  const candidates = items
    .filter((i) => i.status === "queued" && !i.gid && isRetryReady(i, now))
    .sort((a, b) => {
      const pa = Number(a.priority ?? 0);
      const pb = Number(b.priority ?? 0);
      return pb - pa;
    });

  const remaining = cap > 0 ? Math.max(0, cap - activeCount) : candidates.length;
  const toStart = candidates.slice(0, remaining);
  const prefs = dispatchPrefsFrom(declaration);

  const started: Array<{ id: string; gid: string }> = [];
  const failed: Array<{ id: string; error: string }> = [];

  for (const item of toStart) {
    try {
      const gid = await dispatchDownload(deps.aria2, item, {
        capBytesPerSec: deps.capBytesPerSec,
        prefs,
      });
      item.gid = gid;
      item.status = "active";
      started.push({ id: item.id, gid });
      await deps.actionLog.record({
        action: "start",
        target: "queue_item",
        outcome: "changed",
        reason: "scheduler_tick",
        detail: { item_id: item.id, gid, url: item.url },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      failed.push({ id: item.id, error: message });
      await deps.actionLog.record({
        action: "start_failed",
        target: "queue_item",
        outcome: "failed",
        reason: "rpc_error",
        detail: { item_id: item.id, url: item.url, error: message },
      });
    }
  }

  if (started.length > 0 || failed.length > 0) {
    await deps.queueStore.save(items);
  }

  // BG-28(a): point state.active_gid / active_url at the most recently
  // dispatched item so the dashboard knows which row to spotlight. If
  // nothing started this tick we leave the existing values alone — poll
  // is responsible for clearing them when the active item terminates.
  if (started.length > 0 && deps.stateStore) {
    const last = started[started.length - 1]!;
    const lastItem = items.find((i) => i.id === last.id);
    if (lastItem) {
      await deps.stateStore.update((s) => {
        s.active_gid = last.gid;
        s.active_url = lastItem.url ?? null;
      });
    }
  }

  return { started, failed, saturated: false };
}

/**
 * Convenience filter: terminal items the scheduler shouldn't touch
 * (used by callers when computing "what's still in flight").
 */
export const isTerminalStatus = (status: string | undefined | null): boolean =>
  TERMINAL_STATUSES.has(String(status ?? "") as never);
