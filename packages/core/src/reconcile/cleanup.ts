import type { QueueItemRecord } from "../queue/types.js";
import { comparePreference, mergeQueueRows, normalizeQueueRow } from "./merge.js";

export interface CleanupResult {
  changed: boolean;
  items: QueueItemRecord[];
  removed: number;
  normalized: number;
}

/**
 * Pure decision step for queue cleanup: dedupe rows by gid or url,
 * normalize status/live_status pairs, and merge duplicates so the
 * surviving row carries the best fields from both. Mirrors the
 * in-storage half of reconcile.cleanup_queue_state — caller persists
 * the result.
 */
export function planCleanup(items: QueueItemRecord[]): CleanupResult {
  const survivors: QueueItemRecord[] = [];
  let changed = false;
  let normalized = 0;

  for (const item of items) {
    if (normalizeQueueRow(item)) {
      changed = true;
      normalized += 1;
    }
    const gid = String(item.gid ?? "");
    const url = String(item.url ?? "");

    let matchIdx = -1;
    for (let i = 0; i < survivors.length; i++) {
      const ex = survivors[i]!;
      const exGid = String(ex.gid ?? "");
      const exUrl = String(ex.url ?? "");
      if ((gid && exGid && gid === exGid) || (url && exUrl && url === exUrl)) {
        matchIdx = i;
        break;
      }
    }

    if (matchIdx < 0) {
      survivors.push(item);
      continue;
    }

    const match = survivors[matchIdx]!;
    let primary: QueueItemRecord;
    let secondary: QueueItemRecord;
    if (comparePreference(item, match) > 0) {
      survivors[matchIdx] = item;
      primary = item;
      secondary = match;
      changed = true;
    } else {
      primary = match;
      secondary = item;
    }
    if (mergeQueueRows(primary, secondary)) changed = true;
  }

  return {
    changed,
    items: survivors,
    removed: Math.max(items.length - survivors.length, 0),
    normalized,
  };
}
