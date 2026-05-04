const TERMINAL_STATUSES = new Set([
  "complete",
  "error",
  "failed",
  "removed",
]);

const NON_COMPLETE_TERMINAL = new Set(["error", "failed", "removed"]);

export interface QueueItem {
  status?: string | null;
  completed_at?: string | null;
  error_at?: string | null;
  created_at?: string | null;
  [k: string]: unknown;
}

/**
 * Parse an ISO-8601 timestamp; assume UTC if no offset present.
 * Returns epoch seconds, or `fallback` if unparseable.
 */
function parseItemTimestamp(value: string | null | undefined, fallback: number): number {
  if (!value) return fallback;
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value);
  const iso = hasTz ? value : `${value}Z`;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms / 1000 : fallback;
}

function itemTs(item: QueueItem, now: number): number {
  return parseItemTimestamp(
    (item.completed_at ?? item.error_at ?? item.created_at ?? "") as string,
    now,
  );
}

/** Count items eligible for auto-archival given a max age in hours. */
export function countArchivable(
  items: QueueItem[],
  opts: { maxDoneAgeHours?: number; now?: number } = {},
): number {
  const maxDoneAgeHours = opts.maxDoneAgeHours ?? 168;
  const now = opts.now ?? Date.now() / 1000;
  const cutoff = now - maxDoneAgeHours * 3600;
  let n = 0;
  for (const item of items) {
    if (!TERMINAL_STATUSES.has(String(item.status ?? ""))) continue;
    if (itemTs(item, now) < cutoff) n++;
  }
  return n;
}

interface ArchivePlan {
  keep: QueueItem[];
  archive: QueueItem[];
}

/**
 * Pure decision step extracted from state.auto_cleanup_queue: split items
 * into keep / archive given age cutoff and max-complete cap. No I/O.
 */
export function planAutoCleanup(
  items: QueueItem[],
  opts: {
    maxDoneAgeDays?: number;
    maxDoneAgeHours?: number;
    maxDoneCount?: number;
    archiveNonComplete?: boolean;
    now?: number;
  } = {},
): ArchivePlan {
  const now = opts.now ?? Date.now() / 1000;
  const ageHours = opts.maxDoneAgeHours ?? (opts.maxDoneAgeDays ?? 7) * 24;
  const cutoff = now - ageHours * 3600;
  const maxDoneCount = opts.maxDoneCount ?? 100;
  const archiveNonComplete = opts.archiveNonComplete ?? true;

  const keep: QueueItem[] = [];
  const archive: QueueItem[] = [];

  for (const item of items) {
    const status = String(item.status ?? "");
    const isComplete = status === "complete";
    const isOtherTerminal = NON_COMPLETE_TERMINAL.has(status);
    if (isComplete || (archiveNonComplete && isOtherTerminal)) {
      if (itemTs(item, now) < cutoff) {
        archive.push(item);
        continue;
      }
    }
    keep.push(item);
  }

  if (maxDoneCount > 0) {
    const done = keep.filter((i) => i.status === "complete");
    if (done.length > maxDoneCount) {
      const excess = done.length - maxDoneCount;
      const toArchive = new Set(done.slice(0, excess));
      const newKeep: QueueItem[] = [];
      for (const it of keep) {
        if (toArchive.has(it)) archive.push(it);
        else newKeep.push(it);
      }
      keep.length = 0;
      keep.push(...newKeep);
    }
  }

  return { keep, archive };
}
