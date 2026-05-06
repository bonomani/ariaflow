import { basename } from "node:path";
import type { Aria2Client } from "./client.js";
import { addMetalink, addTorrent, addUri, type Aria2Options } from "./methods.js";
import { aria2SpeedValue } from "../bandwidth/units.js";
import type { QueueItemRecord } from "../queue/types.js";
import { prefValue, type Declaration } from "../contracts/declaration.js";

export interface DispatchPrefs {
  /** aria2 `max-tries` global override (default 5). */
  max_tries?: number;
  /** aria2 `retry-wait` seconds (default 10). */
  retry_wait?: number;
}

/**
 * Read dispatch-relevant prefs out of a declaration.
 */
export function dispatchPrefsFrom(declaration: Declaration): DispatchPrefs {
  return {
    max_tries: Number(prefValue(declaration, "aria2_max_tries", 5)) || 5,
    retry_wait: Number(prefValue(declaration, "aria2_retry_wait", 10)) || 10,
  };
}

/**
 * Hand a queue item to aria2 using the appropriate RPC for its mode.
 * Returns the resulting GID (the first GID for metalink batches).
 *
 * Pure-async: takes the client + resolved prefs + bandwidth cap as
 * inputs; no storage, no contracts read.
 */
export async function dispatchDownload(
  client: Aria2Client,
  item: QueueItemRecord,
  opts: { capBytesPerSec: number; prefs: DispatchPrefs },
): Promise<string> {
  const options = baseOptions(item, opts);
  const mode = item.mode ?? "http";
  const url = item.url;

  if (mode === "torrent_data") {
    const data = item.torrent_data;
    if (!data) throw new Error("torrent_data mode but no torrent_data provided");
    options["pause-metadata"] = "true";
    return addTorrent(client, data, [], options);
  }

  if (mode === "metalink_data") {
    const data = item.metalink_data;
    if (!data) throw new Error("metalink_data mode but no metalink_data provided");
    const gids = await addMetalink(client, data, options);
    const first = Array.isArray(gids) ? gids[0] : (gids as unknown as string);
    if (!first) throw new Error("aria2.addMetalink returned no GIDs");
    return first;
  }

  if (mode === "mirror") {
    const mirrors = item.mirrors ?? [];
    const uris = uniq([url, ...mirrors.map(String)]);
    return addUri(client, uris.length ? uris : [url], options);
  }

  if (mode === "torrent" || mode === "metalink" || mode === "magnet") {
    options["pause-metadata"] = "true";
  }
  return addUri(client, [url], options);
}

function baseOptions(
  item: QueueItemRecord,
  opts: { capBytesPerSec: number; prefs: DispatchPrefs },
): Aria2Options {
  const options: Aria2Options = {
    "max-download-limit": aria2SpeedValue(opts.capBytesPerSec),
    continue: "true",
    "max-tries": String(opts.prefs.max_tries ?? 5),
    "retry-wait": String(opts.prefs.retry_wait ?? 10),
  };
  // BG-55: per-item override from /api/downloads/:id/confirm so the
  // operator can reclaim an existing path. Default (BG-54) is aria2's
  // safe rename; this only flips when the operator explicitly confirms.
  if (item.allow_overwrite) options["allow-overwrite"] = "true";

  const output = (item.output ?? "").trim();
  // Only set `out` when output is a bare filename (no path component);
  // anything with a directory belongs in `dir`, set elsewhere.
  if (output && basename(output) === output) options.out = output;

  const selected = item.selected_files ?? [];
  if (Array.isArray(selected) && selected.length > 0) {
    options["select-file"] = selected.join(",");
  }

  if (String(item.desired_state ?? "").trim().toLowerCase() === "paused") {
    options.pause = "true";
  }
  return options;
}

function uniq<T>(arr: T[]): T[] {
  return Array.from(new Set(arr));
}
