import { prefValue, type Declaration } from "../contracts/declaration.js";
import type { ActionLog } from "../storage/action-log.js";
import type { DeclarationStore } from "../storage/declaration.js";
import type { QueueStore } from "../storage/queue.js";
import type { QueueItemRecord } from "../queue/types.js";

export interface RetryDeps {
  queueStore: QueueStore;
  declarationStore: DeclarationStore;
  actionLog: ActionLog;
}

export interface RetryResult {
  /** Items flipped from "error" back to "queued" with a fresh retry_at. */
  rescheduled: Array<{ id: string; retry_count: number; retry_at: string }>;
  /** Items at or above max_retries — left as "error". */
  exhausted: Array<{ id: string; retry_count: number }>;
}

const isFiniteNum = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);

const numberPref = (decl: Declaration, name: string, fallback: number): number => {
  const raw = prefValue(decl, name, fallback);
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
};

/**
 * Walk the queue and pick errored items eligible for retry. For each:
 *   - if retry_count < max_retries: flip status -> "queued", clear gid +
 *     error fields, stamp retry_at = now + backoff * retry_count, bump
 *     retry_count, record "retry_scheduled".
 *   - else: leave as "error", count under exhausted, record "retry_exhausted"
 *     once per item (idempotent — we only emit when the item lacks the
 *     retry_exhausted_at stamp).
 *
 * Pure of RPC concerns: the actual aria2 re-add happens on the next
 * runSchedulerTick once the row is back in "queued" with
 * retry_at <= now.
 */
export async function runRetryPass(deps: RetryDeps, now: number = Date.now()): Promise<RetryResult> {
  const declaration = await deps.declarationStore.load();
  const maxRetries = Math.max(0, Math.trunc(numberPref(declaration, "max_retries", 3)));
  const backoffSec = Math.max(1, Math.trunc(numberPref(declaration, "retry_backoff_seconds", 30)));

  if (maxRetries === 0) {
    return { rescheduled: [], exhausted: [] };
  }

  const items = await deps.queueStore.load();
  const rescheduled: RetryResult["rescheduled"] = [];
  const exhausted: RetryResult["exhausted"] = [];
  let dirty = false;

  for (const item of items) {
    if (item.status !== "error") continue;
    const rec = item as Record<string, unknown>;
    const currentRetries = isFiniteNum(rec.retry_count) ? rec.retry_count : 0;
    if (currentRetries >= maxRetries) {
      if (!rec.retry_exhausted_at) {
        rec.retry_exhausted_at = new Date(now).toISOString();
        dirty = true;
        await deps.actionLog.record({
          action: "retry_exhausted",
          target: "queue_item",
          outcome: "unchanged",
          reason: "max_retries_reached",
          detail: { item_id: item.id, retry_count: currentRetries, max_retries: maxRetries },
        });
      }
      exhausted.push({ id: item.id, retry_count: currentRetries });
      continue;
    }
    const nextCount = currentRetries + 1;
    const delayMs = backoffSec * nextCount * 1000;
    const retryAt = new Date(now + delayMs).toISOString();
    rec.retry_count = nextCount;
    rec.retry_at = retryAt;
    item.status = "queued";
    item.gid = null;
    item.live_status = null;
    item.error_code = null;
    item.error_message = null;
    item.error_at = null;
    dirty = true;
    rescheduled.push({ id: item.id, retry_count: nextCount, retry_at: retryAt });
    await deps.actionLog.record({
      action: "retry_scheduled",
      target: "queue_item",
      outcome: "changed",
      reason: "auto_retry",
      detail: {
        item_id: item.id,
        retry_count: nextCount,
        retry_at: retryAt,
        max_retries: maxRetries,
      },
    });
  }

  if (dirty) await deps.queueStore.save(items);
  return { rescheduled, exhausted };
}

/**
 * Test: is a queued item eligible for the next dispatch? An item with a
 * future `retry_at` timestamp must wait — the tick filter calls this.
 */
export function isRetryReady(item: QueueItemRecord, now: number = Date.now()): boolean {
  const rec = item as Record<string, unknown>;
  const retryAt = rec.retry_at;
  if (typeof retryAt !== "string" || !retryAt) return true;
  const ms = Date.parse(retryAt);
  return !Number.isFinite(ms) || ms <= now;
}
