import { TERMINAL_STATUSES, type QueueItemRecord } from "./types.js";

/**
 * Find an existing live (non-terminal) item with the same source URL —
 * used for add-time deduplication.
 */
export function findLiveItemByUrl(
  items: QueueItemRecord[],
  url: string,
): QueueItemRecord | null {
  for (const it of items) {
    if (it.url === url && !TERMINAL_STATUSES.has(String(it.status ?? "") as never)) {
      return it;
    }
  }
  return null;
}
