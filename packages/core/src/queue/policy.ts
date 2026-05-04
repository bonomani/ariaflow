import { ITEM_STATUSES, type DownloadMode, type ItemStatus, type QueueItemRecord } from "./types.js";

const ALLOWED_ACTIONS: Record<ItemStatus, readonly string[]> = {
  discovering: [],
  queued: ["pause", "remove"],
  waiting: ["pause", "remove"],
  active: ["pause", "remove"],
  paused: ["resume", "remove"],
  complete: ["remove"],
  error: ["retry", "remove"],
  removed: ["retry", "remove"],
};

/**
 * Actions the UI/CLI is permitted to invoke on an item in this status.
 * Returns a fresh array; unknown statuses produce an empty list.
 */
export function allowedActions(status: string): string[] {
  return [...((ALLOWED_ACTIONS as Record<string, readonly string[]>)[status] ?? [])];
}

/**
 * Classify a download URL / payload into the aria2 ingestion mode.
 * Precedence:
 *   torrent_data > metalink_data > mirror > magnet > torrent > metalink > http.
 */
export function detectDownloadMode(opts: {
  url: string;
  mirrors?: string[] | null;
  torrentData?: string | null;
  metalinkData?: string | null;
}): DownloadMode {
  if (opts.torrentData) return "torrent_data";
  if (opts.metalinkData) return "metalink_data";
  if (opts.mirrors && opts.mirrors.length > 1) return "mirror";
  const lower = opts.url.toLowerCase().replace(/[?&#]+$/, "");
  if (lower.startsWith("magnet:")) return "magnet";
  if (lower.endsWith(".torrent")) return "torrent";
  if (lower.endsWith(".metalink") || lower.endsWith(".meta4")) return "metalink";
  return "http";
}

/**
 * Count items by status, plus a `total` field. Statuses with zero items
 * are still emitted so callers get a stable shape.
 */
export function summarizeQueue(items: QueueItemRecord[]): Record<string, number> {
  const counts: Record<string, number> = { total: items.length };
  for (const status of ITEM_STATUSES) {
    counts[status] = items.filter((i) => i.status === status).length;
  }
  return counts;
}
