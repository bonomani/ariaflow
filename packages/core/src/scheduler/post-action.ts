import { ACTIONS, TARGETS } from "../storage/actions.js";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Aria2Client } from "../aria2/client.js";
import { addTorrent, getGlobalOption } from "../aria2/methods.js";
import { prefValue } from "../contracts/declaration.js";
import type { ActionLog } from "../storage/action-log.js";
import type { DeclarationStore } from "../storage/declaration.js";
import type { QueueStore } from "../storage/queue.js";
import { buildPrivateTorrent } from "../torrent/build.js";
import type { QueueItemRecord } from "../queue/types.js";

export interface PostActionDeps {
  queueStore: QueueStore;
  declarationStore: DeclarationStore;
  actionLog: ActionLog;
  aria2: Aria2Client;
}

export interface PostActionResult {
  item_id: string;
  success: boolean;
  reason: string;
  detail?: string;
  distribute?:
    | {
        success: true;
        seed_gid: string;
        infohash: string;
        torrent_path: string;
        piece_count: number;
        tracker: string;
      }
    | { success: false; reason: string };
}

/**
 * Run the configured post-action policy for a single completed item.
 *
 * Today this implements only the auto-distribute branch: when the
 * item carries `distribute=true` (or
 * the global pref `distribute_completed_downloads` is set) AND an
 * `internal_tracker_url` is configured AND the item is HTTP-source,
 * read the downloaded file off disk, build a private .torrent in
 * memory, write it to disk under the configured `torrent_dir`
 * (defaulting to "<dir>/<file>.torrent"), and hand it to aria2 as a
 * new addTorrent call so the daemon starts seeding.
 *
 * Persists the distribute_* fields onto the queue row so /api/torrents
 * can list it and /api/torrents/:hash.torrent can serve the file.
 *
 * Other post_action_rule values (e.g. "pending") are no-ops today —
 * matching the Python pre-1.0 behavior. Errors anywhere in the flow
 * land on result.distribute.reason without throwing.
 */
export async function runPostAction(
  deps: PostActionDeps,
  itemId: string,
): Promise<PostActionResult> {
  const items = await deps.queueStore.load();
  const item = items.find((i) => i.id === itemId);
  if (!item) {
    return {
      item_id: itemId,
      success: false,
      reason: "not_found",
      detail: "queue item missing",
    };
  }

  const declaration = await deps.declarationStore.load();
  const result: PostActionResult = {
    item_id: itemId,
    success: true,
    reason: String(item.post_action_rule ?? "pending"),
    detail: "post action policy not defined yet",
  };

  const shouldDistribute =
    Boolean(item.distribute) ||
    Boolean(prefValue(declaration, "distribute_completed_downloads", false));
  const trackerUrl = String(prefValue(declaration, "internal_tracker_url", "") || "");
  const isHttpSource =
    item.mode === "http" || item.mode === undefined || (item.mode as string) === "";
  if (!shouldDistribute || !trackerUrl || !isHttpSource) {
    return result;
  }

  try {
    let downloadDir: string;
    try {
      const opts = await getGlobalOption(deps.aria2);
      downloadDir = String(opts.dir ?? "") || ".";
    } catch {
      downloadDir = ".";
    }

    const fallbackName = item.url?.split("/").pop()?.split("?")[0] ?? "";
    const fileName = (item.output ?? "") || fallbackName;
    if (!fileName) {
      result.distribute = { success: false, reason: "no filename" };
      await deps.queueStore.save(items);
      return result;
    }
    const filePath = join(downloadDir, fileName);
    if (!existsSync(filePath)) {
      result.distribute = { success: false, reason: `file not found: ${filePath}` };
      return result;
    }

    const fileBytes = readFileSync(filePath);
    const built = buildPrivateTorrent({
      name: fileName,
      fileBytes,
      trackerUrl,
      comment: `ariaflow-server distribute: ${item.url}`,
    });

    const torrentDirPref = String(prefValue(declaration, "torrent_dir", "") || "");
    const torrentDir = torrentDirPref || dirname(filePath);
    mkdirSync(torrentDir, { recursive: true });
    const torrentPath = join(torrentDir, `${fileName}.torrent`);
    writeFileSync(torrentPath, built.torrentBytes);

    const torrentB64 = Buffer.from(built.torrentBytes).toString("base64");
    const seedRatio = String(prefValue(declaration, "distribute_seed_ratio", 0) ?? 0);
    const seedGid = await addTorrent(deps.aria2, torrentB64, [], {
      "seed-ratio": seedRatio,
      dir: downloadDir,
    });

    item.distribute_status = "seeding";
    item.distribute_infohash = built.infohash;
    item.distribute_seed_gid = seedGid;
    item.distribute_torrent_path = torrentPath;
    item.distribute_started_at = new Date().toISOString();
    await deps.queueStore.save(items);

    result.distribute = {
      success: true,
      seed_gid: seedGid,
      infohash: built.infohash,
      torrent_path: torrentPath,
      piece_count: built.pieceCount,
      tracker: trackerUrl,
    };
    await deps.actionLog.record({
      action: ACTIONS.queueDistributeStarted,
      target: TARGETS.queueItem,
      outcome: "changed",
      reason: "post_action",
      detail: {
        item_id: item.id,
        infohash: built.infohash,
        seed_gid: seedGid,
        torrent_path: torrentPath,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    result.distribute = { success: false, reason: message };
  }
  return result;
}

/**
 * Iterate the items the poll pass just transitioned to "complete" and
 * fire runPostAction on each. Idempotent against repeated calls
 * thanks to the distribute_status=="seeding" guard inside the body.
 */
export async function runPostActionBatch(
  deps: PostActionDeps,
  completedIds: readonly string[],
): Promise<PostActionResult[]> {
  const out: PostActionResult[] = [];
  for (const id of completedIds) {
    out.push(await runPostAction(deps, id));
  }
  return out;
}

