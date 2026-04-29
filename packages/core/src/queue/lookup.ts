import { TERMINAL_STATUSES, type QueueItemRecord } from "./types.js";

/**
 * Find a queue item by stable item id (uuid). Returns the array, the
 * matched item, and its index — mirrors queue_ops._find_queue_item_by_id.
 */
export function findItemById(
  items: QueueItemRecord[],
  itemId: string,
): { items: QueueItemRecord[]; item: QueueItemRecord | null; index: number } {
  const index = items.findIndex((i) => i.id === itemId);
  return { items, item: index >= 0 ? items[index]! : null, index };
}

/**
 * Find an item by aria2 GID, ignoring terminal statuses. Mirrors
 * queue_ops.find_queue_item_by_gid.
 */
export function findItemByGid(
  items: QueueItemRecord[],
  gid: string,
): QueueItemRecord | null {
  for (const it of items) {
    if (it.gid === gid && !TERMINAL_STATUSES.has(String(it.status ?? "") as never)) {
      return it;
    }
  }
  return null;
}

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
