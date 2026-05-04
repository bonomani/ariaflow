import type { QueueItemRecord } from "../queue/types.js";

const coerceFloat = (v: unknown): number | null => {
  if (v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

/**
 * Extract the source URL from an aria2 tellStatus payload's `files[0]`
 * by walking files[0].uris[*].uri, falling back to files[0].path.
 */
export function activeItemUrl(info: unknown): string | null {
  if (!info || typeof info !== "object") return null;
  const files = (info as { files?: unknown }).files;
  if (!Array.isArray(files) || files.length === 0) return null;
  const first = files[0];
  if (!first || typeof first !== "object") return null;
  const uris = (first as { uris?: unknown }).uris;
  if (Array.isArray(uris)) {
    for (const u of uris) {
      if (u && typeof u === "object") {
        const uri = (u as { uri?: unknown }).uri;
        if (typeof uri === "string" && uri) return uri;
      }
    }
  }
  const path = (first as { path?: unknown }).path;
  return typeof path === "string" && path ? path : null;
}

/** Map aria2's loose `status` field to the queue's status vocabulary. */
export function mergeActiveStatus(status: string | null | undefined): string {
  if (status === "active") return "active";
  if (status === "paused" || status === "waiting" || status === "complete" || status === "error")
    return status;
  return status ?? "active";
}

/**
 * Tuple used to choose which of two duplicate rows survives during
 * cleanup. Lexicographic comparison: status_rank, completed_length,
 * has_gid, recovered. Higher tuple wins.
 */
export function queueItemPreference(
  item: QueueItemRecord,
): [number, number, number, number] {
  const ranks: Record<string, number> = {
    active: 3,
    waiting: 2,
    paused: 2,
    queued: 1,
    complete: 0,
    error: 0,
  };
  const status = String(item.status ?? "");
  return [
    ranks[status] ?? 0,
    coerceFloat(item.completed_length) ?? 0,
    item.gid ? 1 : 0,
    (item as Record<string, unknown>).recovered ? 1 : 0,
  ];
}

export function comparePreference(a: QueueItemRecord, b: QueueItemRecord): number {
  const ap = queueItemPreference(a);
  const bp = queueItemPreference(b);
  for (let i = 0; i < ap.length; i++) {
    if (ap[i]! > bp[i]!) return 1;
    if (ap[i]! < bp[i]!) return -1;
  }
  return 0;
}

/** Merge string-valued `candidate` fields into `primary` only where empty.  */
const STRING_KEYS = [
  "url",
  "output",
  "post_action_rule",
  "session_id",
  "error_code",
  "error_message",
  "live_status",
  "created_at",
] as const;

const RECOVERY_KEYS = ["recovery_session_id", "recovered_at"] as const;
const NUMERIC_KEYS = ["download_speed", "completed_length", "total_length"] as const;

/**
 * Merge two duplicate queue rows in place: empty primary fields are
 * filled from candidate; numeric fields take the larger value.
 * Returns true if anything changed.
 */
export function mergeQueueRows(primary: QueueItemRecord, candidate: QueueItemRecord): boolean {
  let changed = false;
  const primaryStatus = String(primary.status ?? "").toLowerCase();
  const p = primary as Record<string, unknown>;
  const c = candidate as Record<string, unknown>;

  for (const key of STRING_KEYS) {
    if (!p[key] && c[key]) {
      p[key] = c[key];
      changed = true;
    }
  }
  if (primaryStatus !== "complete" && primaryStatus !== "error") {
    for (const key of RECOVERY_KEYS) {
      if (!p[key] && c[key]) {
        p[key] = c[key];
        changed = true;
      }
    }
  }
  for (const key of NUMERIC_KEYS) {
    const cv = c[key];
    if (cv === null || cv === undefined) continue;
    const cn = coerceFloat(cv) ?? 0;
    const pn = coerceFloat(p[key]) ?? 0;
    if (p[key] === null || p[key] === undefined || cn > pn) {
      p[key] = cv;
      changed = true;
    }
  }
  if (!p.files && c.files) {
    p.files = c.files;
    changed = true;
  }
  if (c.recovered && !p.recovered) {
    p.recovered = true;
    changed = true;
  }
  return changed;
}

/**
 * Normalize a single queue row so live_status/status/recovery flags
 * agree. Returns true on any in-place mutation.
 */
export function normalizeQueueRow(item: QueueItemRecord): boolean {
  let changed = false;
  const status = String(item.status ?? "").toLowerCase();
  const live = String(item.live_status ?? "").toLowerCase();

  if (status === "paused" && (live === "active" || live === "waiting")) {
    item.live_status = "paused";
    changed = true;
  } else if (status === "error") {
    if (live !== "error") {
      item.live_status = "error";
      changed = true;
    }
  } else if (status === "complete" && item.live_status !== undefined && item.live_status !== null) {
    delete (item as Record<string, unknown>).live_status;
    changed = true;
  }
  if (status === "complete") {
    const r = item as Record<string, unknown>;
    for (const k of ["recovered", "recovered_at", "recovery_session_id"]) {
      if (r[k] !== undefined && r[k] !== null) {
        delete r[k];
        changed = true;
      }
    }
  }
  return changed;
}
