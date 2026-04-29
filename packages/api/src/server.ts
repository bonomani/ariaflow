import Fastify, { type FastifyInstance } from "fastify";
import {
  ActionLog,
  allowedActions,
  Aria2Client,
  buildTransferSummary,
  DeclarationStore,
  errorPayload,
  evaluatePreflight,
  getActiveProgress,
  parseAddItems,
  QueueStore,
  rankActiveInfos,
  SessionService,
  StateStore,
  summarizeQueue,
  validateItemId,
  type Declaration,
  type ParsedAddItem,
  type QueueOps,
} from "@ariaflow/core";

export interface ServerDeps {
  queueOps: QueueOps;
  queueStore: QueueStore;
  declarationStore: DeclarationStore;
  stateStore: StateStore;
  sessionService: SessionService;
  actionLog: ActionLog;
  /** aria2 client; if omitted, /api/active and /api/preflight degrade gracefully. */
  aria2?: Aria2Client;
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

  app.get("/api/preflight", async () => {
    const declaration = await deps.declarationStore.load();
    const queueReadable = true; // we just opened the store
    let aria2Available = false;
    if (deps.aria2) {
      try {
        await deps.aria2.call("aria2.getVersion");
        aria2Available = true;
      } catch {
        aria2Available = false;
      }
    }
    const state = await deps.stateStore.load();
    const result = evaluatePreflight(declaration, {
      aria2_available: aria2Available,
      queue_readable: queueReadable,
      paused: state.paused,
    });
    return { ok: true, ...result };
  });

  app.get("/api/active", async () => {
    const state = await deps.stateStore.load();
    if (!deps.aria2) {
      return { ok: true, active: null, reason: "aria2_unavailable" };
    }
    const progress = await getActiveProgress(deps.aria2, state);
    if (progress) return { ok: true, active: progress };
    // Fall back to picking the best candidate from tellActive
    try {
      const infos = await deps.aria2.call<unknown[]>("aria2.tellActive");
      const ranked = rankActiveInfos(infos as Parameters<typeof rankActiveInfos>[0]);
      if (ranked.length > 0) {
        const top = ranked[0]!;
        return { ok: true, active: buildTransferSummary(top, null, { recovered: true }) };
      }
    } catch {
      /* aria2 unreachable — fall through */
    }
    return { ok: true, active: null };
  });

  app.get("/api/sessions/current", async () => {
    const state = await deps.stateStore.load();
    if (!state.session_id) return { ok: true, session: null };
    const stats = await deps.sessionService.stats();
    return { ok: true, session: state, stats };
  });

  app.post("/api/sessions/start", async () => {
    const next = await deps.sessionService.startNew("api_request");
    return { ok: true, session: next };
  });

  app.post("/api/sessions/close", async (_req, reply) => {
    try {
      const closed = await deps.sessionService.close("api_request");
      return { ok: true, session: closed };
    } catch (err) {
      const msg = err instanceof Error ? err.message : "close failed";
      return reply.code(409).send(errorPayload("session_close_blocked", msg));
    }
  });

  app.get("/api/sessions/history", async () => {
    return { ok: true, history: await deps.sessionService.loadHistory() };
  });

  app.put("/api/declaration", async (req, reply) => {
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply.code(400).send(errorPayload("invalid_payload", "expected an object"));
    }
    const incoming = (body as { declaration?: unknown }).declaration ?? body;
    if (!incoming || typeof incoming !== "object" || Array.isArray(incoming)) {
      return reply.code(400).send(errorPayload("invalid_declaration", "declaration must be an object"));
    }
    const meta = (incoming as { meta?: unknown }).meta;
    const uic = (incoming as { uic?: unknown }).uic;
    if (
      !meta ||
      typeof meta !== "object" ||
      !uic ||
      typeof uic !== "object" ||
      !Array.isArray((uic as { preferences?: unknown }).preferences) ||
      !Array.isArray((uic as { gates?: unknown }).gates)
    ) {
      return reply
        .code(400)
        .send(errorPayload("invalid_declaration", "missing meta or uic.{gates,preferences}"));
    }
    const saved = await deps.declarationStore.save(incoming as Declaration);
    return { ok: true, declaration: saved };
  });

  app.get<{ Querystring: { limit?: string } }>("/api/actions", async (req) => {
    const limitRaw = req.query?.limit;
    const limit = Math.min(Math.max(Number(limitRaw) || 200, 1), 5000);
    const entries = await deps.actionLog.load(limit);
    return { ok: true, limit, entries };
  });

  app.get("/api/bandwidth", async () => {
    const declaration = await deps.declarationStore.load();
    const state = await deps.stateStore.load();
    const config = bandwidthConfigFrom(declaration);
    const probe = (state.last_bandwidth_probe ?? null) as Record<string, unknown> | null;
    return {
      ok: true,
      config,
      last_probe: probe,
      last_probe_at: state.last_bandwidth_probe_at ?? null,
      // Surface the most-useful probe fields at top-level for parity
      // with the Python /api/bandwidth response.
      interface: probe?.interface_name ?? null,
      downlink_mbps: probe?.downlink_mbps ?? null,
      uplink_mbps: probe?.uplink_mbps ?? null,
      down_cap_mbps: probe?.down_cap_mbps ?? null,
      up_cap_mbps: probe?.up_cap_mbps ?? null,
      cap_bytes_per_sec: probe?.cap_bytes_per_sec ?? null,
      responsiveness_rpm: probe?.responsiveness_rpm ?? null,
    };
  });

  return app;
}

interface BandwidthConfig {
  down_free_percent: number;
  down_free_absolute_mbps: number;
  down_use_percent: number;
  up_free_percent: number;
  up_free_absolute_mbps: number;
  up_use_percent: number;
  probe_interval_seconds: number;
}

function bandwidthConfigFrom(declaration: Declaration): BandwidthConfig {
  const clampPct = (v: unknown): number =>
    Math.max(0, Math.min(100, Math.trunc(Number(v) || 0)));
  const clampAbs = (v: unknown): number => Math.max(0, Number(v) || 0);
  const get = (name: string, fallback: unknown): unknown => {
    for (const p of declaration.uic?.preferences ?? []) {
      if (p.name === name) return p.value ?? fallback;
    }
    return fallback;
  };
  const downFreePct = clampPct(get("bandwidth_down_free_percent", 20));
  const downFreeAbs = clampAbs(get("bandwidth_down_free_absolute_mbps", 0));
  const upFreePct = clampPct(get("bandwidth_up_free_percent", 50));
  const upFreeAbs = clampAbs(get("bandwidth_up_free_absolute_mbps", 0));
  const interval = Math.max(30, Math.trunc(Number(get("bandwidth_probe_interval_seconds", 180)) || 180));
  return {
    down_free_percent: downFreePct,
    down_free_absolute_mbps: downFreeAbs,
    down_use_percent: 1 - downFreePct / 100,
    up_free_percent: upFreePct,
    up_free_absolute_mbps: upFreeAbs,
    up_use_percent: 1 - upFreePct / 100,
    probe_interval_seconds: interval,
  };
}
