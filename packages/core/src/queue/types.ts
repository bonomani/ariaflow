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
  completed_length?: string | number | null;
  [k: string]: unknown;
}
