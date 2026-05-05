import type { FastifyReply } from "fastify";
import {
  ACTIONS,
  TARGETS,
  allowedActions,
  aria2,
  callStartScheduler,
  errorPayload,
  parseAddItems,
  planAutoCleanup,
  summarizeQueue,
  type ParsedAddItem,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import {
  loadItemOr404,
  requireAria2,
  requireObjectBody,
  sendNotFound,
  sendRpcError,
  validateIdParam,
  type RouteContext,
} from "./_context.js";

export function registerDownloadsRoutes({ app, deps }: RouteContext): void {

  const addDownloads = async (
    body: unknown,
    reply: FastifyReply,
  ): Promise<unknown> => {
    const parsed = parseAddItems(body, deps.cwd ? { cwd: deps.cwd } : {});
    if ("error" in parsed) return reply.code(400).send(parsed.error);
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
    // If the scheduler loop has drained itself (running=false) and the
    // operator isn't paused, kick it so newly queued items dispatch
    // without needing a manual /resume. Mirrors the auto-start in
    // /api/scheduler/resume so Add-Then-Wait is a coherent UX.
    if (deps.startScheduler) {
      const s = await deps.stateStore.load();
      if (!s.running && !s.paused && created.some((c) => !c.duplicate)) {
        // BG-40: callStartScheduler stamps intent + handles revert.
        // We don't surface its result — failures shouldn't mask a
        // successful add.
        const start = deps.startScheduler;
        await callStartScheduler(deps.stateStore, () => start());
      }
    }
    return reply.code(200).send({ ok: true, items: created });
  };

  app.post("/api/downloads", (req, reply) => addDownloads(req.body, reply));

  app.get("/api/downloads", async () => {
    const items = await deps.queueStore.load();
    return withMeta("GET", "/api/downloads", {
      ok: true,
      summary: summarizeQueue(items),
      items: items.map((i) => ({
        id: i.id,
        url: i.url,
        status: i.status ?? "queued",
        gid: i.gid ?? null,
        actions: allowedActions(String(i.status ?? "")),
      })),
    });
  });

  app.get<{ Querystring: { limit?: string } }>("/api/downloads/archive", async (req, reply) => {
    if (!deps.archiveStore) {
      return reply
        .code(503)
        .send(errorPayload("archive_unavailable", "no archive store wired"));
    }
    const limitRaw = req.query?.limit;
    let limit = 100;
    const n = Number(limitRaw);
    if (Number.isFinite(n)) limit = Math.max(1, Math.min(500, Math.trunc(n)));
    const items = await deps.archiveStore.load();
    return withMeta("GET", "/api/downloads/archive", { ok: true, items: items.slice(-limit) });
  });

  app.post("/api/downloads/cleanup", async (req, reply) => {
    if (!deps.archiveStore) {
      return reply
        .code(503)
        .send(errorPayload("archive_unavailable", "no archive store wired"));
    }
    const body = (req.body && typeof req.body === "object" && !Array.isArray(req.body)
      ? (req.body as Record<string, unknown>)
      : {}) as Record<string, unknown>;
    const maxAge = Number.isFinite(Number(body.max_done_age_days))
      ? Number(body.max_done_age_days)
      : 7;
    const maxCount = Number.isFinite(Number(body.max_done_count))
      ? Number(body.max_done_count)
      : 100;
    const items = await deps.queueStore.load();
    const plan = planAutoCleanup(items as never, {
      maxDoneAgeDays: maxAge,
      maxDoneCount: maxCount,
    });
    if (plan.archive.length > 0) {
      const archived = await deps.archiveStore.load();
      const stamped = plan.archive.map((it: Record<string, unknown>) => ({
        ...it,
        archived_at: new Date().toISOString(),
      })) as unknown as Awaited<ReturnType<typeof deps.archiveStore.load>>;
      await deps.archiveStore.save([...archived, ...stamped]);
      await deps.queueStore.save(plan.keep as never);
      await deps.actionLog.record({
        action: ACTIONS.queueAutoCleanup,
        target: TARGETS.queue,
        outcome: "changed",
        reason: "stale_items_archived",
        before: { total: items.length },
        after: { total: plan.keep.length, archived: plan.archive.length },
        detail: {
          max_done_age_days: maxAge,
          max_done_count: maxCount,
        },
      });
    }
    return { ok: true, archived: plan.archive.length, remaining: plan.keep.length };
  });

  app.get<{ Params: { id: string } }>("/api/downloads/:id", async (req, reply) => {
    const found = await loadItemOr404(deps, req.params.id, reply);
    if (!found) return;
    const { item } = found;
    return {
      ok: true,
      item,
      actions: allowedActions(String(item.status ?? "")),
    };
  });

  const removeItem = async (
    id: string,
    reply: FastifyReply,
  ): Promise<unknown> => {
    if (!validateIdParam(id, reply)) return;
    const removed = await deps.queueOps.remove(id);
    if (!removed) return sendNotFound(reply);
    return { ok: true, id: removed.id };
  };

  app.delete<{ Params: { id: string } }>("/api/downloads/:id", (req, reply) =>
    removeItem(req.params.id, reply),
  );

  app.post<{ Params: { id: string } }>("/api/downloads/:id/pause", async (req, reply) => {
    if (!validateIdParam(req.params.id, reply)) return;
    const next = await deps.queueOps.transitionStatus(req.params.id, "paused", "paused_at");
    if (!next) return sendNotFound(reply);
    return { ok: true, item: next };
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/priority", async (req, reply) => {
    const obj = requireObjectBody(req.body, reply, "expected {priority: number}");
    if (!obj) return;
    const raw = obj.priority;
    const priority = Number(raw);
    if (!Number.isFinite(priority)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_priority", "priority must be a finite number"));
    }
    const found = await loadItemOr404(deps, req.params.id, reply);
    if (!found) return;
    const { items, item } = found;
    item.priority = Math.trunc(priority);
    await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: ACTIONS.queueSetPriority,
      target: TARGETS.queueItem,
      outcome: "changed",
      reason: "api_request",
      detail: { item_id: item.id, priority: item.priority },
    });
    return { ok: true, id: item.id, priority: item.priority };
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/retry", async (req, reply) => {
    const found = await loadItemOr404(deps, req.params.id, reply);
    if (!found) return;
    const { items, item } = found;
    const before = { ...item };
    // Reset failure fields and re-queue. The aria2-side re-add lives in
    // the deferred scheduler integration.
    item.status = "queued";
    item.error_code = null;
    item.error_message = null;
    item.error_at = null;
    item.gid = null;
    item.live_status = null;
    await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: ACTIONS.queueRetry,
      target: TARGETS.queueItem,
      outcome: "changed",
      reason: "api_request",
      before: { item: before },
      after: { item: { ...item } },
      detail: { item_id: item.id },
    });
    return { ok: true, item };
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/resume", async (req, reply) => {
    if (!validateIdParam(req.params.id, reply)) return;
    const next = await deps.queueOps.transitionStatus(req.params.id, "queued", "resumed_at");
    if (!next) return sendNotFound(reply);
    return { ok: true, item: next };
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/files", async (req, reply) => {
    const obj = requireObjectBody(req.body, reply, "expected {select: [1, 3, 5]}");
    if (!obj) return;
    const select = obj.select;
    if (!Array.isArray(select) || select.length === 0) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {select: [1, 3, 5]}"));
    }
    const indices: number[] = [];
    for (const v of select) {
      const n = Number(v);
      if (!Number.isFinite(n)) {
        return reply
          .code(400)
          .send(errorPayload("invalid_indices", "select entries must be integers"));
      }
      indices.push(Math.trunc(n));
    }
    const found = await loadItemOr404(deps, req.params.id, reply);
    if (!found) return;
    const { items, item } = found;
    const before = item.selected_files ?? null;
    item.selected_files = indices;
    await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: ACTIONS.queueSelectFiles,
      target: TARGETS.queueItem,
      outcome: "changed",
      reason: "user_select_files",
      detail: { item_id: item.id, before, after: indices },
    });
    // The aria2-side select-file change requires changeOption(gid, ...);
    // when an aria2 client is wired and the item has a gid, push it now.
    if (deps.aria2 && item.gid) {
      try {
        await aria2.changeOption(deps.aria2, item.gid, {
          "select-file": indices.join(","),
        });
      } catch {
        /* RPC errors don't block the local mutation — caller can retry */
      }
    }
    return { ok: true, item_id: item.id, selected_files: indices };
  });

  app.get<{ Params: { id: string } }>("/api/downloads/:id/files", async (req, reply) => {
    const found = await loadItemOr404(deps, req.params.id, reply);
    if (!found) return;
    const { item } = found;
    const gid = item.gid;
    if (!gid) {
      return reply.code(409).send(errorPayload("no_gid", "item has no aria2 GID"));
    }
    if (requireAria2(deps, reply)) return;
    try {
      const files = await aria2.getFiles(deps.aria2!, gid);
      return { ok: true, item_id: item.id, gid, files };
    } catch (err) {
      return sendRpcError(reply, err);
    }
  });
}
