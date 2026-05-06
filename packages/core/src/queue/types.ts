// BG-30/BG-33: aria2-native vocabulary (active/waiting/paused/error/complete/removed),
// plus two backend-only pre-aria2 staging states (discovering/queued).
export const ITEM_STATUSES = [
  "discovering",
  "queued",
  "awaiting_confirmation",
  "waiting",
  "active",
  "paused",
  "complete",
  "error",
  "removed",
] as const;

export type ItemStatus = (typeof ITEM_STATUSES)[number];

export const TERMINAL_STATUSES: ReadonlySet<ItemStatus> = new Set([
  "complete",
  "error",
  "removed",
]);

export type DownloadMode =
  | "http"
  | "magnet"
  | "torrent"
  | "metalink"
  | "mirror"
  | "torrent_data"
  | "metalink_data";

export interface QueueItemRecord {
  id: string;
  url: string;
  output?: string | null;
  post_action_rule?: string;
  status?: ItemStatus | string;
  desired_state?: "running" | "paused" | string;
  priority?: number;
  mode?: DownloadMode;
  mirrors?: string[] | null;
  torrent_data?: string | null;
  metalink_data?: string | null;
  selected_files?: number[] | null;
  created_at?: string;
  gid?: string | null;
  session_id?: string | null;
  recovery_session_id?: string | null;
  recovered_at?: string | null;
  live_status?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  paused_at?: string | null;
  resumed_at?: string | null;
  completed_at?: string | null;
  error_at?: string | null;
  removed_at?: string | null;
  session_history?: Array<Record<string, string>> | null;
  /**
   * Recovery / retry bookkeeping. Set by the scheduler reconcile +
   * retry passes when an item is adopted from a stale aria2 session
   * or scheduled for re-dispatch.
   */
  recovered?: boolean;
  retry_at?: string | null;
  retry_count?: number;
  retry_exhausted_at?: string | null;
  /** File listing populated by the aria2 poller (per-file metadata). */
  files?: unknown[];
  /**
   * BG-55: absolute path aria2 wrote the completed file to, captured
   * from `tellStatus(gid).files[0].path` at completion. Used by the
   * re-add gate's filesystem-first verification (best-effort hint;
   * the gate stats the FS directly, so a missing field is fine).
   */
  output_path?: string | null;
  /** BG-55: optional ETag captured at completion (Tier 2 verification). */
  remote_etag?: string | null;
  /** BG-55: optional Last-Modified captured at completion (Tier 2 verification). */
  remote_last_modified?: string | null;
  /**
   * BG-56: false after the operator deletes the on-disk file via
   * `/api/files`. Stays undefined for items whose file is on disk
   * (default-true semantics — absence = present).
   */
  file_present_on_disk?: boolean;
  /**
   * BG-55: per-item override forwarded to aria2 as `allow-overwrite`.
   * Set true by `POST /api/downloads/:id/confirm` so the operator can
   * reclaim the existing path; defaults to undefined (aria2 default
   * behavior of auto-rename via BG-54).
   */
  allow_overwrite?: boolean;
  /**
   * BG-28(b): live progress fields mirrored from aria2's tellStatus
   * (camelCase to match the dashboard's wire shape — these are the
   * canonical names, the snake_case aliases were retired). Optional
   * because rows that have never been polled won't have them. aria2
   * RPC delivers strings; the dedup/merge path may persist a Number
   * after an arithmetic compare, so the type is union (callers
   * Number() at read time anyway).
   */
  downloadSpeed?: string | number;
  uploadSpeed?: string | number;
  completedLength?: string | number;
  totalLength?: string | number;
  connections?: number;
  numSeeders?: string | number;
  /**
   * Distribution / seeding fields stamped by the post-action seed flow.
   * Optional because most items never become seed sources. Surfaced by
   * `/api/torrents` and the seed-stop / torrent-file routes.
   */
  distribute?: boolean;
  distribute_status?: "seeding" | "stopped";
  distribute_infohash?: string;
  distribute_seed_gid?: string;
  distribute_torrent_path?: string;
  distribute_started_at?: string;
  [k: string]: unknown;
}
