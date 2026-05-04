import type { Aria2Status } from "../aria2/methods.js";

export interface TransferSummary {
  gid: string;
  url: string | null;
  status?: string;
  error_code?: string;
  error_message?: string;
  download_speed?: string;
  completed_length?: string;
  total_length?: string;
  files?: unknown;
  percent: number;
  recovered?: true;
}

const num = (v: unknown): number => {
  const n = typeof v === "number" ? v : Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
};

/**
 * Build the TransferSummary shape used by the /api/active endpoint
 * and CLI status output, given an aria2 tellStatus payload + a known
 * URL. Percent is computed only when totalLength > 0.
 */
export function buildTransferSummary(
  info: Aria2Status,
  url: string | null,
  opts: { recovered?: boolean } = {},
): TransferSummary {
  const total = num(info.totalLength);
  const done = num(info.completedLength);
  const percent = total > 0 ? Math.round((done / total) * 1000) / 10 : 0;

  const out: TransferSummary = {
    gid: info.gid,
    url,
    percent,
  };
  if (typeof info.status === "string") out.status = info.status;
  if (typeof info.errorCode === "string") out.error_code = info.errorCode;
  if (typeof info.errorMessage === "string") out.error_message = info.errorMessage;
  if (typeof info.downloadSpeed === "string") out.download_speed = info.downloadSpeed;
  if (typeof info.completedLength === "string") out.completed_length = info.completedLength;
  if (typeof info.totalLength === "string") out.total_length = info.totalLength;
  if (info.files !== undefined) out.files = info.files;
  if (opts.recovered) out.recovered = true;
  return out;
}

/**
 * Sort active aria2 jobs to pick the most-likely "primary" one when the
 * server lost track of active_gid. The Python version sorts by
 * (percent_complete, completed, speed) descending — we replicate the
 * tuple comparison via a 3-key compare.
 */
export function rankActiveInfos(infos: Aria2Status[]): Aria2Status[] {
  const score = (i: Aria2Status): [number, number, number] => {
    const total = Math.max(num(i.totalLength), 1);
    const done = num(i.completedLength);
    return [done / total, done, num(i.downloadSpeed)];
  };
  return [...infos].sort((a, b) => {
    const sa = score(a);
    const sb = score(b);
    for (let k = 0; k < sa.length; k++) {
      if (sa[k]! < sb[k]!) return 1;
      if (sa[k]! > sb[k]!) return -1;
    }
    return 0;
  });
}
