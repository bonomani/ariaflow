import type { QueueItemRecord } from "../queue/types.js";
import { activeItemUrl } from "./merge.js";

const TERMINAL_FOR_MATCH = new Set(["complete", "error"]);

const urlTail = (url: string): string =>
  url.split("?")[0]!.replace(/\/+$/, "").split("/").pop() ?? "";

/**
 * Find the queue row that corresponds to an aria2 active job.
 *
 * Matching strategy (mirrors reconcile._queue_item_for_active_info):
 *   1. exact gid match across all items
 *   2. exact url match across all items
 *   3. tail-of-path url match across all items
 *   then restrict candidates to non-terminal rows; if a session_id is
 *   provided, also restrict to rows in that session (or with no session)
 *   when at least one such row exists, and re-run gid / url / tail
 *   matching against the narrowed pool.
 */
export function queueItemForActiveInfo(
  info: { gid?: unknown; files?: unknown },
  items: QueueItemRecord[],
  sessionId?: string | null,
): QueueItemRecord | null {
  const gid = String(info.gid ?? "");
  const url = activeItemUrl(info);
  const tail = url ? urlTail(url) : "";

  if (gid) {
    const m = items.find((i) => i.gid === gid);
    if (m) return m;
  }
  if (url) {
    const exact = items.find((i) => i.url === url);
    if (exact) return exact;
    if (tail) {
      const byTail = items.find((i) => {
        const cur = String(i.url ?? "");
        return cur && (cur === url || urlTail(cur) === tail);
      });
      if (byTail) return byTail;
    }
  }

  let candidates = items.filter(
    (i) => !TERMINAL_FOR_MATCH.has(String(i.status ?? "")),
  );
  if (sessionId) {
    const scoped = candidates.filter(
      (i) => !i.session_id || i.session_id === sessionId,
    );
    if (scoped.length > 0) candidates = scoped;
  }

  if (gid) {
    const m = candidates.find((i) => i.gid === gid);
    if (m) return m;
  }
  if (url) {
    const exact = candidates.find((i) => i.url === url);
    if (exact) return exact;
    if (tail) {
      const byTail = candidates.find((i) => {
        const cur = String(i.url ?? "");
        return cur && (cur === url || urlTail(cur) === tail);
      });
      if (byTail) return byTail;
    }
  }
  return null;
}
