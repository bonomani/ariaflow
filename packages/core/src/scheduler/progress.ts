import type { Aria2Client } from "../aria2/client.js";
import { tellStatus } from "../aria2/methods.js";
import type { ServerState } from "../storage/state.js";

export interface ActiveProgress {
  gid: string;
  url: string | null;
  status?: string;
  download_speed?: number;
  completed_length?: number;
  total_length?: number;
  percent: number | null;
  error_code?: string;
  error_message?: string;
  error?: string;
}

/**
 * Probe aria2 for the currently-active item's progress. Returns null
 * when no `active_gid` is recorded; returns a partial result with `error`
 * set when the RPC call throws.
 */
export async function getActiveProgress(
  client: Aria2Client,
  state: ServerState,
): Promise<ActiveProgress | null> {
  const gid = state.active_gid;
  if (!gid) return null;
  try {
    const info = await tellStatus(client, gid);
    const total = Number(info.totalLength ?? 0);
    const completed = Number(info.completedLength ?? 0);
    const speed = Number(info.downloadSpeed ?? 0);
    const percent = total > 0 ? Math.round((completed / total) * 10000) / 100 : null;
    const out: ActiveProgress = {
      gid,
      url: state.active_url,
      percent,
      download_speed: speed,
      completed_length: completed,
      total_length: total,
    };
    if (typeof info.status === "string") out.status = info.status;
    if (typeof info.errorCode === "string") out.error_code = info.errorCode;
    if (typeof info.errorMessage === "string") out.error_message = info.errorMessage;
    return out;
  } catch (err) {
    return {
      gid,
      url: state.active_url,
      percent: null,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
