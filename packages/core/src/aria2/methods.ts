import type { Aria2Client } from "./client.js";

export type Aria2Options = Record<string, string>;

export interface Aria2Status {
  gid: string;
  status: string;
  totalLength?: string;
  completedLength?: string;
  downloadSpeed?: string;
  uploadSpeed?: string;
  errorCode?: string;
  errorMessage?: string;
  [k: string]: unknown;
}

const trimmedParams = (
  base: unknown[],
  options: Aria2Options | undefined,
  position: number | undefined,
): unknown[] => {
  const params: unknown[] = [...base];
  if (options !== undefined || position !== undefined) params.push(options ?? {});
  if (position !== undefined) params.push(position);
  return params;
};

// ── add ────────────────────────────────────────────────────────────
export const addUri = (
  c: Aria2Client,
  uris: string[],
  options?: Aria2Options,
  position?: number,
): Promise<string> => c.call("aria2.addUri", trimmedParams([uris], options, position));

export const addTorrent = (
  c: Aria2Client,
  torrentB64: string,
  uris: string[] = [],
  options?: Aria2Options,
  position?: number,
): Promise<string> => c.call("aria2.addTorrent", trimmedParams([torrentB64, uris], options, position));

export const addMetalink = (
  c: Aria2Client,
  metalinkB64: string,
  options?: Aria2Options,
  position?: number,
): Promise<string[]> =>
  c.call("aria2.addMetalink", trimmedParams([metalinkB64], options, position));

// ── pause / unpause / remove ───────────────────────────────────────
export const pause = (c: Aria2Client, gid: string) => c.call<string>("aria2.pause", [gid]);
export const forcePause = (c: Aria2Client, gid: string) =>
  c.call<string>("aria2.forcePause", [gid]);
export const pauseAll = (c: Aria2Client) => c.call<string>("aria2.pauseAll");
export const forcePauseAll = (c: Aria2Client) => c.call<string>("aria2.forcePauseAll");
export const unpause = (c: Aria2Client, gid: string) => c.call<string>("aria2.unpause", [gid]);
export const unpauseAll = (c: Aria2Client) => c.call<string>("aria2.unpauseAll");
export const remove = (c: Aria2Client, gid: string) => c.call<string>("aria2.remove", [gid]);
export const forceRemove = (c: Aria2Client, gid: string) =>
  c.call<string>("aria2.forceRemove", [gid]);
export const removeDownloadResult = (c: Aria2Client, gid: string) =>
  c.call<string>("aria2.removeDownloadResult", [gid]);
export const purgeDownloadResult = (c: Aria2Client) =>
  c.call<string>("aria2.purgeDownloadResult");

// ── tell* ──────────────────────────────────────────────────────────
export const tellStatus = (c: Aria2Client, gid: string, fields?: string[]) =>
  c.call<Aria2Status>("aria2.tellStatus", fields ? [gid, fields] : [gid]);

export const tellActive = (c: Aria2Client, fields?: string[]) =>
  c.call<Aria2Status[]>("aria2.tellActive", fields ? [fields] : []);

export const tellWaiting = (
  c: Aria2Client,
  offset: number,
  num: number,
  fields?: string[],
) =>
  c.call<Aria2Status[]>(
    "aria2.tellWaiting",
    fields ? [offset, num, fields] : [offset, num],
  );

export const tellStopped = (
  c: Aria2Client,
  offset: number,
  num: number,
  fields?: string[],
) =>
  c.call<Aria2Status[]>(
    "aria2.tellStopped",
    fields ? [offset, num, fields] : [offset, num],
  );

// ── get* (per-gid metadata) ────────────────────────────────────────
export const getFiles = (c: Aria2Client, gid: string) =>
  c.call<unknown[]>("aria2.getFiles", [gid]);
export const getUris = (c: Aria2Client, gid: string) =>
  c.call<unknown[]>("aria2.getUris", [gid]);
export const getPeers = (c: Aria2Client, gid: string) =>
  c.call<unknown[]>("aria2.getPeers", [gid]);
export const getServers = (c: Aria2Client, gid: string) =>
  c.call<unknown[]>("aria2.getServers", [gid]);
export const getOption = (c: Aria2Client, gid: string) =>
  c.call<Record<string, string>>("aria2.getOption", [gid]);
export const changeOption = (
  c: Aria2Client,
  gid: string,
  options: Aria2Options,
) => c.call<string>("aria2.changeOption", [gid, options]);

// ── global ─────────────────────────────────────────────────────────
export const getGlobalOption = (c: Aria2Client) =>
  c.call<Record<string, string>>("aria2.getGlobalOption");
export const changeGlobalOption = (c: Aria2Client, options: Aria2Options) =>
  c.call<string>("aria2.changeGlobalOption", [options]);
export const getGlobalStat = (c: Aria2Client) =>
  c.call<Record<string, string>>("aria2.getGlobalStat");
export const getVersion = (c: Aria2Client) =>
  c.call<{ version: string; enabledFeatures: string[] }>("aria2.getVersion");
export const getSessionInfo = (c: Aria2Client) =>
  c.call<{ sessionId: string }>("aria2.getSessionInfo");
export const saveSession = (c: Aria2Client) => c.call<string>("aria2.saveSession");
export const shutdown = (c: Aria2Client) => c.call<string>("aria2.shutdown");
export const forceShutdown = (c: Aria2Client) => c.call<string>("aria2.forceShutdown");
export const listMethods = (c: Aria2Client) => c.call<string[]>("system.listMethods");
export const listNotifications = (c: Aria2Client) =>
  c.call<string[]>("system.listNotifications");

// ── position / uri mutation ────────────────────────────────────────
export const changePosition = (
  c: Aria2Client,
  gid: string,
  pos: number,
  how: "POS_SET" | "POS_CUR" | "POS_END" = "POS_SET",
) => c.call<number>("aria2.changePosition", [gid, pos, how]);

export const changeUri = (
  c: Aria2Client,
  gid: string,
  fileIndex: number,
  delUris: string[],
  addUris: string[],
  position?: number,
) =>
  c.call<[number, number]>(
    "aria2.changeUri",
    position !== undefined
      ? [gid, fileIndex, delUris, addUris, position]
      : [gid, fileIndex, delUris, addUris],
  );

// ── system.multicall ───────────────────────────────────────────────
export interface MulticallEntry {
  methodName: string;
  params?: unknown[];
}
export const multicall = (c: Aria2Client, calls: MulticallEntry[]) =>
  c.call<unknown[]>("system.multicall", [calls.map((m) => ({ methodName: m.methodName, params: m.params ?? [] }))]);

// ── speed/seed setters ─────────────────────────────────────────────
import { aria2SpeedValue } from "../bandwidth/units.js";

export const setMaxOverallDownloadLimit = (c: Aria2Client, capBytesPerSec: number) =>
  changeGlobalOption(c, { "max-overall-download-limit": aria2SpeedValue(capBytesPerSec) });
export const setMaxOverallUploadLimit = (c: Aria2Client, capBytesPerSec: number) =>
  changeGlobalOption(c, { "max-overall-upload-limit": aria2SpeedValue(capBytesPerSec) });
export const setMaxDownloadLimit = (c: Aria2Client, gid: string, capBytesPerSec: number) =>
  changeOption(c, gid, { "max-download-limit": aria2SpeedValue(capBytesPerSec) });
export const setMaxUploadLimit = (c: Aria2Client, gid: string, capBytesPerSec: number) =>
  changeOption(c, gid, { "max-upload-limit": aria2SpeedValue(capBytesPerSec) });

export const setSeedRatio = (c: Aria2Client, ratio: number) =>
  changeGlobalOption(c, { "seed-ratio": String(Math.max(0, ratio)) });
export const setSeedTime = (c: Aria2Client, minutes: number) =>
  changeGlobalOption(c, { "seed-time": String(Math.max(0, Math.trunc(minutes))) });
