// BG-30/BG-33: aria2-native vocabulary (active/waiting/paused/error/complete/removed),
// plus two backend-only pre-aria2 staging states (discovering/queued).
export const ITEM_STATUSES = [
  "discovering",
  "queued",
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
