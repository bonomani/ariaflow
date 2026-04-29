import Fastify, { type FastifyInstance } from "fastify";
import {
  errorPayload,
  parseAddItems,
  type ParsedAddItem,
  type QueueOps,
} from "@ariaflow/core";

export interface ServerDeps {
  queueOps: QueueOps;
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

  return app;
}
