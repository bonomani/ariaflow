import { aria2, errorPayload } from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

export function registerTorrentsRoutes({ app, deps }: RouteContext): void {
  app.get("/api/torrents", async () => {
    const items = await deps.queueStore.load();
    const seeds: Array<Record<string, unknown>> = [];
    for (const item of items) {
      const infohash = (item as Record<string, unknown>).distribute_infohash;
      const status = (item as Record<string, unknown>).distribute_status;
      if (status === "seeding" && typeof infohash === "string" && infohash) {
        const fallbackName = item.url?.split("/").pop()?.split("?")[0] ?? "";
        seeds.push({
          infohash,
          name: item.output || fallbackName,
          url: item.url ?? null,
          seed_gid: (item as Record<string, unknown>).distribute_seed_gid ?? null,
          torrent_url: `/api/torrents/${infohash}.torrent`,
          started_at: (item as Record<string, unknown>).distribute_started_at ?? null,
          item_id: item.id,
        });
      }
    }
    return withMeta("GET", "/api/torrents", { ok: true, torrents: seeds, count: seeds.length });
  });

  app.post<{ Params: { infohash: string } }>(
    "/api/torrents/:infohash/stop",
    async (req, reply) => {
      const infohash = req.params.infohash.trim();
      if (!infohash) {
        return reply.code(400).send(errorPayload("invalid_payload", "infohash required"));
      }
      const items = await deps.queueStore.load();
      const item = items.find(
        (i) =>
          (i as Record<string, unknown>).distribute_infohash === infohash &&
          (i as Record<string, unknown>).distribute_status === "seeding",
      );
      if (!item) {
        return reply.code(404).send(errorPayload("not_found", `no active seed for ${infohash}`));
      }
      const itemRec = item as Record<string, unknown>;
      const seedGid = itemRec.distribute_seed_gid;
      if (typeof seedGid === "string" && seedGid && deps.aria2) {
        try {
          await aria2.remove(deps.aria2, seedGid);
        } catch {
          /* RPC failure shouldn't block the local mutation */
        }
      }
      const torrentPath = itemRec.distribute_torrent_path;
      if (typeof torrentPath === "string" && torrentPath) {
        try {
          const { unlinkSync, existsSync } = await import("node:fs");
          if (existsSync(torrentPath)) unlinkSync(torrentPath);
        } catch {
          /* best-effort cleanup */
        }
      }
      itemRec.distribute_status = "stopped";
      delete itemRec.distribute_seed_gid;
      await deps.queueStore.save(items);
      await deps.actionLog.record({
        action: "seed_stopped",
        target: "queue_item",
        outcome: "changed",
        reason: "user_stop_seed",
        after: { item_id: item.id, infohash },
        detail: { item_id: item.id, infohash },
      });
      return { ok: true, infohash, status: "stopped" };
    },
  );

  app.get<{ Params: { file: string } }>("/api/torrents/:file", async (req, reply) => {
    const file = req.params.file;
    if (!file.endsWith(".torrent")) {
      return reply.code(404).send(errorPayload("not_found", "torrent not found"));
    }
    const infohash = file.slice(0, -".torrent".length);
    const items = await deps.queueStore.load();
    const match = items.find(
      (i) => (i as Record<string, unknown>).distribute_infohash === infohash,
    );
    const torrentPath =
      match && (match as Record<string, unknown>).distribute_torrent_path;
    if (!match || typeof torrentPath !== "string") {
      return reply.code(404).send(errorPayload("not_found", "torrent not found"));
    }
    const { existsSync, readFileSync } = await import("node:fs");
    if (!existsSync(torrentPath)) {
      return reply.code(404).send(errorPayload("not_found", "torrent not found"));
    }
    const body = readFileSync(torrentPath);
    reply.header("Access-Control-Allow-Origin", "*");
    reply.type("application/x-bittorrent");
    return reply.send(body);
  });
}
