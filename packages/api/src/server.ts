import Fastify, { type FastifyInstance } from "fastify";
import {
  allowedActions,
  DeclarationStore,
  errorPayload,
  parseAddItems,
  QueueStore,
  summarizeQueue,
  validateItemId,
  type ParsedAddItem,
  type QueueOps,
} from "@ariaflow/core";

export interface ServerDeps {
  queueOps: QueueOps;
  queueStore: QueueStore;
  declarationStore: DeclarationStore;
  /** Optional override for the cwd used during output path validation. */
  cwd?: string;
  logger?: boolean;
}

/**
 * Build a Fastify instance wired with the migrated routes. The caller
 * owns the storage stack (lock, stores, ops) and passes it in — keeps
 * this layer free of singletons and easy to unit-test.
 */
export function buildServer(deps: ServerDeps): FastifyInstance {
  const app = Fastify({ logger: deps.logger ?? false });

  app.setNotFoundHandler((req, reply) => {
    reply.code(404).send(errorPayload("not_found", "resource not found"));
  });

  app.post("/api/downloads", async (req, reply) => {
    const parsed = parseAddItems(req.body, deps.cwd ? { cwd: deps.cwd } : {});
    if ("error" in parsed) {
      return reply.code(400).send(parsed.error);
    }
    const created: Array<{ id: string; url: string; status: string; duplicate: boolean }> = [];
    for (const item of parsed.items as ParsedAddItem[]) {
      const { item: rec, duplicate } = await deps.queueOps.add({
        url: item.url,
        output: item.output,
        post_action_rule: item.post_action_rule,
        mirrors: item.mirrors,
        torrent_data: item.torrent_data,
        metalink_data: item.metalink_data,
        priority: item.priority,
        distribute: item.distribute,
      });
      created.push({
        id: rec.id,
        url: rec.url,
        status: String(rec.status ?? "queued"),
        duplicate,
      });
    }
    return reply.code(200).send({ ok: true, items: created });
  });

  app.get("/api/downloads", async () => {
    const items = await deps.queueStore.load();
    return {
      ok: true,
      summary: summarizeQueue(items),
      items: items.map((i) => ({
        id: i.id,
        url: i.url,
        status: i.status ?? "queued",
        gid: i.gid ?? null,
        actions: allowedActions(String(i.status ?? "")),
      })),
    };
  });

  app.get<{ Params: { id: string } }>("/api/downloads/:id", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const items = await deps.queueStore.load();
    const item = items.find((i) => i.id === req.params.id);
    if (!item) return reply.code(404).send(errorPayload("not_found", "item not found"));
    return {
      ok: true,
      item,
      actions: allowedActions(String(item.status ?? "")),
    };
  });

  app.delete<{ Params: { id: string } }>("/api/downloads/:id", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const removed = await deps.queueOps.remove(req.params.id);
    if (!removed) return reply.code(404).send(errorPayload("not_found", "item not found"));
    return { ok: true, id: removed.id };
  });

  app.get("/api/declaration", async () => {
    const declaration = await deps.declarationStore.load();
    return { ok: true, declaration };
  });

  return app;
}
