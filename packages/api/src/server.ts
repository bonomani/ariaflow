import Fastify, { type FastifyInstance } from "fastify";
import fastifyCors from "@fastify/cors";
import {
  listFreshness,
  registerDefaultFreshness,
  withMeta,
} from "./freshness.js";
import { eventMatchesTopics, parseTopics } from "./event-topics.js";
import {
  ActionLog,
  allowedActions,
  aria2,
  ArchiveStore,
  PeerRegistry,
  planAutoCleanup,
  Aria2Client,
  bandwidthConfigFrom,
  bandwidthUnits,
  buildTransferSummary,
  DeclarationStore,
  detectServiceTarget,
  errorPayload,
  EventBus,
  evaluatePreflight,
  findAria2c,
  getActiveProgress,
  install as installNs,
  installAria2Service,
  MANAGED_ARIA2_OPTIONS,
  parseAddItems,
  prefValue,
  QueueStore,
  rankActiveInfos,
  runBandwidthProbe,
  SAFE_ARIA2_OPTIONS,
  scheduler as schedulerHelpers,
  SessionService,
  StateStore,
  summarizeQueue,
  uninstallAria2Service,
  validateChangeOptions,
  validateItemId,
  type Declaration,
  type ParsedAddItem,
  type QueueOps,
} from "@ariaflow/core";
import { generateOpenApi } from "./openapi.js";

export interface ServerDeps {
  queueOps: QueueOps;
  queueStore: QueueStore;
  archiveStore?: ArchiveStore;
  declarationStore: DeclarationStore;
  stateStore: StateStore;
  sessionService: SessionService;
  actionLog: ActionLog;
  /** Optional version string surfaced at /api/version (default "0.0.0"). */
  version?: string;
  /** Path to openapi.yaml on disk; if omitted, /api/openapi.yaml 404s. */
  openapiYamlPath?: string;
  /**
   * CORS origin policy. `true` (default) echoes the request's Origin
   * header; pass `"*"` to send a wildcard, an array of allowed origins
   * to gate the response, or `false` to disable CORS entirely.
   */
  cors?: boolean | string | string[];
  /** Optional EventBus; if provided, /api/events streams its publish() calls. */
  eventBus?: EventBus;
  /** Optional peer registry; if omitted, /api/peers returns an empty list. */
  peerRegistry?: PeerRegistry;
  /** aria2 client; if omitted, /api/active and /api/preflight degrade gracefully. */
  aria2?: Aria2Client;
  /** Optional override for the cwd used during output path validation. */
  cwd?: string;
  logger?: boolean;
  /**
   * BG-25: lifecycle hooks for the scheduler loop. When wired, the
   * /api/scheduler/{start,stop} routes (and /resume's auto-start) drive
   * these so the dashboard can flip `state.running` truthfully.
   * `state.running` means "the scheduler loop is actively dispatching"
   * — the same semantic the dashboard's `schedulerStateLabel()` reads.
   */
  startScheduler?: () => Promise<{ started: boolean; reason: string }>;
  stopScheduler?: () => Promise<{ stopped: boolean; reason: string }>;
  /**
   * Optional override for the bandwidth probe entry point. Defaults to
   * `core.runBandwidthProbe`. Tests pass a stub so they don't spawn the
   * real macOS `networkQuality` binary (which can take 10s+).
   */
  runBandwidthProbe?: typeof import("@ariaflow/core").runBandwidthProbe;
}

const SWAGGER_UI_HTML = `<!DOCTYPE html>
<html><head>
  <meta charset="utf-8">
  <title>ariaflow-server API</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head><body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: '/api/openapi.yaml',
      dom_id: '#swagger-ui',
      deepLinking: true,
    });
  </script>
</body></html>
`;

/**
 * Build a Fastify instance wired with the migrated routes. The caller
 * owns the storage stack (lock, stores, ops) and passes it in — keeps
 * this layer free of singletons and easy to unit-test.
 */
export function buildServer(deps: ServerDeps): FastifyInstance {
  const app = Fastify({ logger: deps.logger ?? false });

  // BG-31: per-endpoint freshness contract. Stamps `meta` on a curated
  // subset of GETs and exposes the registry at /api/_meta. Idempotent.
  registerDefaultFreshness();

  // CORS: echo the request Origin by default so the Swagger UI / dashboard
  // running on a different host or port can hit /api/* without preflight
  // surprises. Callers can pass a string / array to scope it, or `false`
  // to disable entirely.
  if (deps.cors !== false) {
    const cors = deps.cors ?? true;
    void app.register(fastifyCors, {
      origin: cors,
      methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
      allowedHeaders: ["Content-Type", "If-None-Match"],
      exposedHeaders: ["ETag", "X-Request-Id", "X-Schema-Version"],
    });
  }

  // Capture full registered URLs for the OpenAPI introspector. Fastify's
  // printRoutes() formats output as a tree with relative leaf segments
  // that's awkward to parse; the onRoute hook fires once per route with
  // the full url, so we just record them here.
  const recorded: Array<{ method: string | string[]; url: string }> = [];
  (app as unknown as { _ariaflowRoutes: typeof recorded })._ariaflowRoutes = recorded;
  app.addHook("onRoute", (route) => {
    recorded.push({ method: route.method, url: route.url });
  });

  // OpenAPI path-template overrides: a few routes use a Fastify catch-all
  // segment (e.g. `:file`) that should map to a more specific spec path.
  // The introspector reads this map when emitting `paths`.
  (app as unknown as { _ariaflowOpenApiPathOverrides: Map<string, string> })
    ._ariaflowOpenApiPathOverrides = new Map<string, string>([
    ["/api/torrents/:file", "/api/torrents/{infohash}.torrent"],
  ]);

  // BG-24: in-memory metrics powering /api/status.health (Developer
  // tab chips). Counters are best-effort — restart resets them; we
  // don't try to persist across server lifetimes.
  const metrics = {
    startedAt: Date.now(),
    requestsTotal: 0,
    errorsTotal: 0,
    sseClients: 0,
    bytesReceivedTotal: 0,
    bytesSentTotal: 0,
  };
  app.addHook("onRequest", async (req) => {
    metrics.requestsTotal += 1;
    const len = Number(req.headers["content-length"] ?? 0);
    if (Number.isFinite(len) && len > 0) metrics.bytesReceivedTotal += len;
  });
  app.addHook("onResponse", async (_req, reply) => {
    if (reply.statusCode >= 400) metrics.errorsTotal += 1;
    const sent = Number(reply.getHeader("content-length") ?? 0);
    if (Number.isFinite(sent) && sent > 0) metrics.bytesSentTotal += sent;
  });

  if (deps.eventBus) {
    deps.actionLog.setBus(deps.eventBus);
    deps.sessionService.setBus(deps.eventBus);
  }

  app.setNotFoundHandler((req, reply) => {
    reply.code(404).send(errorPayload("not_found", "resource not found"));
  });

  const addDownloads = async (
    body: unknown,
    reply: import("fastify").FastifyReply,
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
        try {
          await deps.startScheduler();
        } catch {
          /* swallow — surfacing failures here would mask a successful add */
        }
      }
    }
    return reply.code(200).send({ ok: true, items: created });
  };

  app.post("/api/downloads", (req, reply) => addDownloads(req.body, reply));
  // openapi.yaml documents /api/downloads/add as the canonical add
  // endpoint; /api/downloads is the alias. Both are kept wired.
  app.post("/api/downloads/add", (req, reply) => addDownloads(req.body, reply));

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
        action: "auto_cleanup",
        target: "queue",
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

  const removeItem = async (
    id: string,
    reply: import("fastify").FastifyReply,
  ): Promise<unknown> => {
    if (!validateItemId(id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const removed = await deps.queueOps.remove(id);
    if (!removed) return reply.code(404).send(errorPayload("not_found", "item not found"));
    return { ok: true, id: removed.id };
  };

  app.delete<{ Params: { id: string } }>("/api/downloads/:id", (req, reply) =>
    removeItem(req.params.id, reply),
  );

  app.post<{ Params: { id: string } }>("/api/downloads/:id/pause", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const next = await deps.queueOps.transitionStatus(req.params.id, "paused", "paused_at");
    if (!next) return reply.code(404).send(errorPayload("not_found", "item not found"));
    return { ok: true, item: next };
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/priority", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply.code(400).send(errorPayload("invalid_payload", "expected {priority: number}"));
    }
    const raw = (body as { priority?: unknown }).priority;
    const priority = Number(raw);
    if (!Number.isFinite(priority)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_priority", "priority must be a finite number"));
    }
    const items = await deps.queueStore.load();
    const item = items.find((i) => i.id === req.params.id);
    if (!item) return reply.code(404).send(errorPayload("not_found", "item not found"));
    item.priority = Math.trunc(priority);
    await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: "set_priority",
      target: "queue_item",
      outcome: "changed",
      reason: "api_request",
      detail: { item_id: item.id, priority: item.priority },
    });
    return { ok: true, id: item.id, priority: item.priority };
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/retry", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const items = await deps.queueStore.load();
    const item = items.find((i) => i.id === req.params.id);
    if (!item) return reply.code(404).send(errorPayload("not_found", "item not found"));
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
      action: "retry",
      target: "queue_item",
      outcome: "changed",
      reason: "api_request",
      before: { item: before },
      after: { item: { ...item } },
      detail: { item_id: item.id },
    });
    return { ok: true, item };
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/resume", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const next = await deps.queueOps.transitionStatus(req.params.id, "queued", "resumed_at");
    if (!next) return reply.code(404).send(errorPayload("not_found", "item not found"));
    return { ok: true, item: next };
  });

  app.get("/api/declaration", async () => {
    const declaration = await deps.declarationStore.load();
    return withMeta("GET", "/api/declaration", { ok: true, declaration });
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

  // openapi.yaml documents /api/sessions (= current session) and
  // /api/sessions/stats as separate endpoints; both are thin views
  // over SessionService and used by the dashboard.
  app.get("/api/sessions", async () => {
    const state = await deps.stateStore.load();
    return withMeta("GET", "/api/sessions", {
      ok: true,
      session: state.session_id ? state : null,
    });
  });

  app.get("/api/sessions/stats", async () => {
    const stats = await deps.sessionService.stats();
    return { ok: true, stats };
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

  const saveDeclaration = async (
    body: unknown,
    reply: import("fastify").FastifyReply,
  ): Promise<unknown> => {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply.code(400).send(errorPayload("invalid_payload", "expected an object"));
    }
    const incoming = (body as { declaration?: unknown }).declaration ?? body;
    if (!incoming || typeof incoming !== "object" || Array.isArray(incoming)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_declaration", "declaration must be an object"));
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
  };

  app.put("/api/declaration", (req, reply) => saveDeclaration(req.body, reply));
  // POST alias documented in openapi.yaml for clients that can't
  // issue PUT.
  app.post("/api/declaration", (req, reply) => saveDeclaration(req.body, reply));

  const patchPreferences = async (
    body: unknown,
    reply: import("fastify").FastifyReply,
  ): Promise<unknown> => {
    if (
      !body ||
      typeof body !== "object" ||
      Array.isArray(body) ||
      Object.keys(body as object).length === 0
    ) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {preference_name: value}"));
    }
    const declaration = await deps.declarationStore.load();
    const preferences = declaration.uic?.preferences ?? [];
    const applied: Record<string, { before: unknown; after: unknown }> = {};
    const unknown: string[] = [];
    for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
      const pref = preferences.find((p) => p.name === key);
      if (!pref) {
        unknown.push(key);
        continue;
      }
      applied[key] = { before: pref.value, after: value };
      pref.value = value;
    }
    if (unknown.length > 0) {
      return reply
        .code(400)
        .send(errorPayload("unknown_preferences", `unknown: ${unknown.join(", ")}`));
    }
    const saved = await deps.declarationStore.save(declaration);
    await deps.actionLog.record({
      action: "patch_preferences",
      target: "declaration",
      outcome: "changed",
      reason: "user_patch_preferences",
      after: { applied },
      detail: { applied },
    });
    return { ok: true, applied, declaration: saved };
  };

  app.post("/api/declaration/preferences", (req, reply) => patchPreferences(req.body, reply));
  // PATCH is the canonical method per openapi.yaml; POST is kept as an
  // alias for clients that can't issue PATCH.
  app.patch("/api/declaration/preferences", (req, reply) => patchPreferences(req.body, reply));

  // Stub /api/tests so the documented endpoint exists. In-server test
  // execution is intentionally out of scope; users run `pnpm test` on
  // the host.
  app.get("/api/tests", async () => ({
    ok: true,
    available: false,
    message: "use 'pnpm test' on the host; in-server test execution is not implemented",
  }));

  app.get<{ Querystring: { limit?: string } }>("/api/actions", async (req) => {
    const limitRaw = req.query?.limit;
    const limit = Math.min(Math.max(Number(limitRaw) || 200, 1), 5000);
    const entries = await deps.actionLog.load(limit);
    return { ok: true, limit, entries };
  });

  // /api/log returns a clamped tail of actions.jsonl in {items} shape.
  // Default limit 120, max 500.
  // BG-24 cosmetic nit: emit `ok: true` so the response is consistent
  // with every other backend endpoint (frontend gate is
  // `data?.ok !== false` so the missing-key form was working, but the
  // shape was inconsistent).
  app.get<{ Querystring: { limit?: string } }>("/api/log", async (req) => {
    const limitRaw = req.query?.limit;
    let limit = 120;
    const n = Number(limitRaw);
    if (Number.isFinite(n)) limit = Math.max(1, Math.min(500, Math.trunc(n)));
    const items = await deps.actionLog.load(limit);
    return withMeta("GET", "/api/log", { ok: true, items });
  });

  app.get("/api/health", async () => {
    return withMeta("GET", "/api/health", {
      ok: true,
      status: "healthy",
      uptime_seconds: Math.round(process.uptime()),
    });
  });

  app.get("/api/version", async () => {
    return withMeta("GET", "/api/version", { ok: true, version: deps.version ?? "0.0.0" });
  });

  // BG-31 #3: machine-readable freshness index for the dashboard's
  // FreshnessRouter. Self-classified `bootstrap` (cache for the
  // session). Generated from the registry — never hand-maintained.
  app.get("/api/_meta", async () => {
    return withMeta("GET", "/api/_meta", { ok: true, endpoints: listFreshness() });
  });

  app.get("/api", async () => ({
    name: "ariaflow-server",
    version: deps.version ?? "0.0.0",
    docs: "/api/docs",
    openapi: "/api/openapi.yaml",
  }));

  app.get<{ Querystring: { status?: string; session?: string } }>(
    "/api/status",
    async (req) => {
      const items = await deps.queueStore.load();
      const state = await deps.stateStore.load();
      const statusFilter = (req.query?.status ?? "").trim();
      const sessionFilter = (req.query?.session ?? "").trim();
      let filtered = items;
      if (statusFilter) {
        const allowed = new Set(statusFilter.split(",").map((s) => s.trim()).filter(Boolean));
        filtered = filtered.filter((i) => allowed.has(String(i.status ?? "")));
      }
      if (sessionFilter === "current") {
        filtered = filtered.filter((i) => i.session_id === state.session_id);
      } else if (sessionFilter) {
        filtered = filtered.filter((i) => i.session_id === sessionFilter);
      }
      // BG-19: identity sub-object the dashboard reads to populate
      // header pills + the offline-state gate. Always set even when the
      // server is the one answering (reachable=true is structurally
      // implied — the frontend's offline detector treats reachable=false
      // as the trigger).
      const identity = {
        reachable: true,
        pid: process.pid,
        version: deps.version ?? "0.0.0",
        error: null,
      };

      // BG-24: server metrics for the Developer-tab chips. disk_ok is
      // resolved from the configured max_disk_usage_percent pref +
      // checkDiskSpace() so a low-disk warning surfaces here too.
      let diskOk = true;
      try {
        const declaration = await deps.declarationStore.load();
        const max = schedulerHelpers.maxDiskPercent(declaration);
        const downloadDirPref = String(
          prefValue(declaration, "download_dir", "") ?? "",
        );
        const probePath = downloadDirPref || process.cwd();
        const { statfsSync } = await import("node:fs");
        diskOk = schedulerHelpers.checkDiskSpace({
          maxPercent: max,
          probe: () => {
            if (typeof statfsSync !== "function") return null;
            try {
              const fs = statfsSync(probePath);
              const total = Number(fs.blocks) * Number(fs.bsize);
              const free = Number(fs.bavail) * Number(fs.bsize);
              return { used: Math.max(0, total - free), total };
            } catch {
              return null;
            }
          },
        }).ok;
      } catch {
        // Best-effort — unknown disk state shouldn't poison the chip.
        diskOk = true;
      }

      const health = {
        uptime_seconds: process.uptime(),
        requests_total: metrics.requestsTotal,
        errors_total: metrics.errorsTotal,
        sse_clients: metrics.sseClients,
        bytes_received_total: metrics.bytesReceivedTotal,
        bytes_sent_total: metrics.bytesSentTotal,
        disk_ok: diskOk,
      };


      // BG-25 sub-issue: lift the live bandwidth probe summary to a
      // top-level `bandwidth` key (mirroring /api/bandwidth's BG-21
      // shape) so the dashboard's Cap chip works on the Dashboard tab
      // without first visiting Bandwidth.
      const probe = (state.last_bandwidth_probe ?? null) as Record<string, unknown> | null;
      const bandwidth = probe
        ? { ...probe, last_probe_at: state.last_bandwidth_probe_at ?? null }
        : null;

      // BG-30 #5: derive active_gid / active_url from aria2.tellActive
      // at read time — the stamped state.active_gid stays as a fallback
      // when the daemon is unreachable, but the live tellActive answer
      // wins so a crash never leaves a phantom gid spotlit on the chip.
      let liveActiveGid: string | null = (state.active_gid as string | null) ?? null;
      let liveActiveUrl: string | null = (state.active_url as string | null) ?? null;
      if (deps.aria2) {
        try {
          const infos = (await deps.aria2.call<unknown[]>("aria2.tellActive")) as Array<
            Record<string, unknown>
          >;
          if (infos.length > 0) {
            const top = infos[0]!;
            const gid = typeof top.gid === "string" ? top.gid : null;
            liveActiveGid = gid;
            const match = gid ? items.find((i) => i.gid === gid) : null;
            liveActiveUrl = match ? match.url ?? null : liveActiveUrl;
          } else {
            liveActiveGid = null;
            liveActiveUrl = null;
          }
        } catch {
          /* aria2 unreachable — keep stamped fallback */
        }
      }

      // BG-33: `dispatch_paused` is the canonical scheduler-pause field
      // (disambiguates from item-level `paused`). Internal storage keeps
      // `state.paused` as the field name; we do not surface it.
      const dispatchPaused = Boolean(state.paused);

      const summary = summarizeQueue(filtered);

      const { paused: _legacyPaused, ...stateRest } = state;
      void _legacyPaused;
      const stateOut: Record<string, unknown> = {
        ...stateRest,
        active_gid: liveActiveGid,
        active_url: liveActiveUrl,
        dispatch_paused: dispatchPaused,
      };

      const payload: Record<string, unknown> = {
        ok: true,
        "ariaflow-server": identity,
        health,
        items: filtered,
        summary,
        state: stateOut,
        bandwidth,
        _rev: Number(state._rev ?? 0),
      };
      return withMeta("GET", "/api/status", payload);
    },
  );

  app.get("/api/openapi.yaml", async (_req, reply) => {
    const yamlPath = deps.openapiYamlPath;
    if (!yamlPath) {
      return reply
        .code(404)
        .send(errorPayload("not_found", "openapi.yaml path not configured"));
    }
    const { existsSync, readFileSync } = await import("node:fs");
    if (!existsSync(yamlPath)) {
      return reply
        .code(404)
        .send(errorPayload("not_found", "openapi.yaml not found on disk"));
    }
    reply.type("application/yaml");
    // BG-37: rewrite info.version to match /api/version so the published
    // contract artifact never drifts from the running release.
    const raw = readFileSync(yamlPath, "utf8");
    const runtimeVersion = deps.version ?? "0.0.0";
    const stamped = raw.replace(
      /^(info:[\s\S]*?\n {2}version:)[^\n]*/m,
      `$1 ${runtimeVersion}`,
    );
    return reply.send(stamped);
  });

  app.get("/api/docs", async (_req, reply) => {
    reply.type("text/html; charset=utf-8");
    return reply.send(SWAGGER_UI_HTML);
  });

  app.get("/api/openapi", async () => {
    return generateOpenApi(app);
  });

  app.get<{ Querystring: { topics?: string } }>("/api/events", async (req, reply) => {
    const bus = deps.eventBus;
    if (!bus) {
      return reply.code(503).send(errorPayload("events_unavailable", "no event bus wired"));
    }
    // BG-32: connect-time topic filter. ?topics=items,scheduler keeps
    // the stream lean for clients that only watch a subset. Empty/missing
    // → all topics (back-compat). Unknown topic names produce an empty
    // subset so a typo doesn't silently widen to a firehose.
    const topics = parseTopics(req.query?.topics);
    // SSE writes via reply.raw.writeHead, which bypasses Fastify's reply
    // pipeline and the @fastify/cors plugin. Echo the CORS headers
    // directly so EventSource clients on a different origin can connect.
    const headers: Record<string, string> = {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    };
    if (deps.cors !== false) {
      const origin = req.headers.origin;
      if (typeof origin === "string" && origin) {
        headers["Access-Control-Allow-Origin"] = origin;
        headers["Vary"] = "Origin";
      } else if (deps.cors === "*" || deps.cors === undefined || deps.cors === true) {
        headers["Access-Control-Allow-Origin"] = "*";
      }
    }
    reply.raw.writeHead(200, headers);
    // Emit a real named "connected" event (not an SSE comment) so
    // consumers using addEventListener("connected", ...) get a
    // deliberate server-says-it's-ready handshake. EventSource onopen
    // fires on header arrival, which doesn't prove the server has
    // accepted the stream past headers — this frame does.
    reply.raw.write(`event: connected\ndata: {}\n\n`);
    let alive = true;
    const writeEvent = (event: string, data: unknown) => {
      if (!alive) return;
      // BG-32: drop events whose topic isn't in the client's filter
      // set. Unknown event names fall through (eventTopics returns
      // ALL_TOPICS) so a new emitter is visible until it's classified.
      if (!eventMatchesTopics(event, topics)) return;
      reply.raw.write(`event: ${event}\n`);
      reply.raw.write(`data: ${JSON.stringify(data)}\n\n`);
    };
    const unsubscribe = bus.subscribe(writeEvent);
    metrics.sseClients += 1;
    const heartbeat = setInterval(() => {
      if (alive) reply.raw.write(`: ping\n\n`);
    }, 15_000);
    let cleanedUp = false;
    const cleanup = () => {
      if (cleanedUp) return;
      cleanedUp = true;
      alive = false;
      clearInterval(heartbeat);
      unsubscribe();
      metrics.sseClients = Math.max(0, metrics.sseClients - 1);
    };
    req.raw.on("close", cleanup);
    reply.raw.on("close", cleanup);
    // Keep the response open — Fastify will resolve once we return,
    // but the underlying socket stays alive thanks to the listeners.
    return reply;
  });

  app.post("/api/bandwidth/probe", async (_req, reply) => {
    const declaration = await deps.declarationStore.load();
    const config = bandwidthConfigFrom(declaration);
    const runProbe = deps.runBandwidthProbe ?? runBandwidthProbe;
    const probeRec = await runProbe({ config });
    const downCap = probeRec.down_cap_mbps;
    const upCap = probeRec.up_cap_mbps;

    await deps.stateStore.update((s) => {
      (s as Record<string, unknown>).last_bandwidth_probe = probeRec as unknown as Record<
        string,
        unknown
      >;
      s.last_bandwidth_probe_at = Date.now() / 1000;
    });

    if (deps.aria2 && typeof probeRec.cap_bytes_per_sec === "number") {
      try {
        await aria2.setMaxOverallDownloadLimit(deps.aria2, probeRec.cap_bytes_per_sec);
      } catch {
        /* RPC failure is logged-only; the probe still applies locally */
      }
      const upCapBytes = Math.trunc(
        Number(probeRec.up_cap_mbps ?? 0) * bandwidthUnits.BYTES_PER_MEGABIT,
      );
      if (upCapBytes > 0) {
        try {
          await aria2.setMaxOverallUploadLimit(deps.aria2, upCapBytes);
        } catch {
          /* same */
        }
      }
    }

    await deps.actionLog.record({
      action: "probe",
      target: "bandwidth",
      outcome: probeRec.source === "networkquality" ? "changed" : "unchanged",
      reason: "manual_probe",
      detail: probeRec as unknown as Record<string, unknown>,
    });

    return reply.send({
      ok: true,
      probe: probeRec,
      config,
      interface_name: probeRec.interface_name ?? null,
      downlink_mbps: probeRec.downlink_mbps,
      uplink_mbps: probeRec.uplink_mbps ?? null,
      down_cap_mbps: downCap,
      up_cap_mbps: upCap,
      current_limit: probeRec.cap_bytes_per_sec ?? null,
      responsiveness_rpm: probeRec.responsiveness_rpm ?? null,
      source: probeRec.source,
    });
  });

  app.get("/api/bandwidth", async () => {
    const declaration = await deps.declarationStore.load();
    const state = await deps.stateStore.load();
    const config = bandwidthConfigFrom(declaration);
    const probe = (state.last_bandwidth_probe ?? null) as Record<string, unknown> | null;
    return withMeta("GET", "/api/bandwidth", {
      ok: true,
      config,
      last_probe: probe,
      last_probe_at: state.last_bandwidth_probe_at ?? null,
      // BG-21: surface probe fields at top level under the names the
      // dashboard's bwInterfaceText / bwSourceText / bwCurrentLimitText
      // helpers read.
      interface_name: probe?.interface_name ?? null,
      source: probe?.source ?? null,
      cap_mbps: probe?.cap_mbps ?? null,
      current_limit: probe?.cap_bytes_per_sec ?? null,
      downlink_mbps: probe?.downlink_mbps ?? null,
      uplink_mbps: probe?.uplink_mbps ?? null,
      down_cap_mbps: probe?.down_cap_mbps ?? null,
      up_cap_mbps: probe?.up_cap_mbps ?? null,
      responsiveness_rpm: probe?.responsiveness_rpm ?? null,
    });
  });

  const requireAria2 = (reply: import("fastify").FastifyReply) => {
    if (deps.aria2) return null;
    reply.code(503).send(errorPayload("aria2_unavailable", "no aria2 client wired"));
    return reply;
  };

  app.get("/api/aria2/option_tiers", async () => {
    const declaration = await deps.declarationStore.load();
    const unsafe = declaration.uic.preferences.find((p) => p.name === "aria2_unsafe_options");
    return {
      ok: true,
      managed: [...MANAGED_ARIA2_OPTIONS].sort(),
      safe: [...SAFE_ARIA2_OPTIONS].sort(),
      unsafe_enabled: Boolean(unsafe?.value),
    };
  });

  // BG-22: the dashboard reads `aria2Options[opt]` straight from the
  // response body (`this.aria2Options = data`), so the options dict
  // must be spread at the top level. aria2 option names are kebab-case
  // ("connect-timeout", "max-tries", ...) so they never collide with
  // our envelope keys (`ok`, `gid`). Same fix for all four endpoints
  // (canonical `get_*` per openapi.yaml + the `global_option` /
  // `option` short-form aliases).
  const globalOptionsHandler = async (
    _req: import("fastify").FastifyRequest,
    reply: import("fastify").FastifyReply,
  ) => {
    if (requireAria2(reply)) return;
    try {
      const opts = await aria2.getGlobalOption(deps.aria2!);
      return withMeta("GET", "/api/aria2/get_global_option", { ok: true, ...opts });
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  };

  const itemOptionsHandler = async (
    req: import("fastify").FastifyRequest<{ Querystring: { gid?: string } }>,
    reply: import("fastify").FastifyReply,
  ) => {
    if (requireAria2(reply)) return;
    const gid = (req.query?.gid ?? "").trim();
    if (!gid) {
      return reply.code(400).send(errorPayload("missing_gid", "gid query parameter required"));
    }
    try {
      const opts = await aria2.getOption(deps.aria2!, gid);
      return { ok: true, gid, ...opts };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  };

  app.get("/api/aria2/get_global_option", globalOptionsHandler);
  app.get("/api/aria2/global_option", globalOptionsHandler);
  app.get<{ Querystring: { gid?: string } }>("/api/aria2/get_option", itemOptionsHandler);
  app.get<{ Querystring: { gid?: string } }>("/api/aria2/option", itemOptionsHandler);

  app.post("/api/aria2/change_global_option", async (req, reply) => {
    if (requireAria2(reply)) return;
    const declaration = await deps.declarationStore.load();
    const validated = validateChangeOptions(req.body, declaration);
    if (!validated.ok) {
      return reply.code(400).send(errorPayload(validated.error, validated.message));
    }
    try {
      const before = await aria2.getGlobalOption(deps.aria2!);
      await aria2.changeGlobalOption(deps.aria2!, validated.options);
      const after = await aria2.getGlobalOption(deps.aria2!);
      await deps.actionLog.record({
        action: "change_options",
        target: "aria2",
        outcome: "changed",
        reason: "user_change_options",
        before: { options: before },
        after: { options: after },
      });
      return { ok: true, applied: validated.options };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

  app.post<{ Params: { id: string } }>("/api/downloads/:id/files", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {select: [1, 3, 5]}"));
    }
    const select = (body as { select?: unknown }).select;
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
    const items = await deps.queueStore.load();
    const item = items.find((i) => i.id === req.params.id);
    if (!item) return reply.code(404).send(errorPayload("not_found", "item not found"));
    const before = item.selected_files ?? null;
    item.selected_files = indices;
    await deps.queueStore.save(items);
    await deps.actionLog.record({
      action: "select_files",
      target: "queue_item",
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
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const items = await deps.queueStore.load();
    const item = items.find((i) => i.id === req.params.id);
    if (!item) return reply.code(404).send(errorPayload("not_found", "item not found"));
    const gid = item.gid;
    if (!gid) {
      return reply.code(409).send(errorPayload("no_gid", "item has no aria2 GID"));
    }
    if (requireAria2(reply)) return;
    try {
      const files = await aria2.getFiles(deps.aria2!, gid);
      return { ok: true, item_id: item.id, gid, files };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

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
    return withMeta("GET", "/api/torrents", { torrents: seeds, count: seeds.length });
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

  app.get("/api/peers", async () => {
    const peers = deps.peerRegistry?.list() ?? [];
    return withMeta("GET", "/api/peers", { ok: true, peers });
  });

  app.get("/api/scheduler", async () => {
    const s = await deps.stateStore.load();
    const running = Boolean(s.running);
    const paused = Boolean(s.paused);
    const status = running && paused ? "paused" : running ? "running" : "starting";
    return {
      status,
      running,
      paused,
      session_id: s.session_id,
      session_started_at: s.session_started_at,
      session_closed_at: s.session_closed_at,
      _rev: Number(s._rev ?? 0),
    };
  });

  app.post("/api/scheduler/pause", async () => {
    const next = await deps.stateStore.update((s) => {
      s.paused = true;
    });
    await deps.actionLog.record({
      action: "pause",
      target: "scheduler",
      outcome: "changed",
      reason: "api_request",
    });
    return { ok: true, paused: next.paused, _rev: Number(next._rev ?? 0) };
  });

  app.post("/api/scheduler/ucc", async () => {
    const declaration = await deps.declarationStore.load();
    let aria2Available = false;
    if (deps.aria2) {
      try {
        await deps.aria2.call("aria2.getVersion");
        aria2Available = true;
      } catch {
        aria2Available = false;
      }
    }
    const stateBefore = await deps.stateStore.load();
    const queueBefore = await deps.queueStore.load();
    const pf = evaluatePreflight(declaration, {
      aria2_available: aria2Available,
      queue_readable: true,
      paused: stateBefore.paused,
    });
    if (pf.exit_code !== 0) {
      const result = {
        observation: "failed",
        outcome: "failed",
        failure_class: "permanent",
        message: "preflight failed",
        reason: "gate_failed",
        observed_before: { gates: pf.gates },
        diff: { failures: pf.hard_failures },
      };
      await deps.actionLog.record({
        action: "ucc",
        target: "queue",
        outcome: result.outcome,
        observation: result.observation,
        reason: result.reason,
        before: { state: stateBefore, queue: summarizeQueue(queueBefore) },
        after: {
          state: await deps.stateStore.load(),
          queue: summarizeQueue(await deps.queueStore.load()),
          ucc: { result, preflight: pf },
        },
        detail: { result, preflight: pf },
      });
      return { meta: { contract: "UCC", version: "2.0" }, result, preflight: pf };
    }

    // Gates passed. The full process_queue() loop lives in the deferred
    // scheduler integration, so the UCC run currently converges on a
    // no-op with the live queue summary as the diff payload.
    const queueAfter = await deps.queueStore.load();
    const result = {
      observation: "ok",
      outcome: "converged",
      message: "queue processed",
      reason: "converged",
      observed_before: { items: queueBefore },
      observed_after: { items: queueAfter },
      diff: {
        count_delta: queueAfter.length - queueBefore.length,
        summary: summarizeQueue(queueAfter),
        active: null,
      },
    };
    await deps.actionLog.record({
      action: "ucc",
      target: "queue",
      outcome: result.outcome,
      observation: result.observation,
      reason: result.reason,
      before: { state: stateBefore, queue: summarizeQueue(queueBefore) },
      after: {
        state: await deps.stateStore.load(),
        queue: summarizeQueue(queueAfter),
        ucc: { result, preflight: pf },
      },
      detail: { result, preflight: pf },
    });
    return { meta: { contract: "UCC", version: "2.0" }, result, preflight: pf };
  });

  app.post("/api/scheduler/preflight", async () => {
    const declaration = await deps.declarationStore.load();
    let aria2Available = false;
    if (deps.aria2) {
      try {
        await deps.aria2.call("aria2.getVersion");
        aria2Available = true;
      } catch {
        aria2Available = false;
      }
    }
    const stateBefore = await deps.stateStore.load();
    const queueBefore = await deps.queueStore.load();
    const result = evaluatePreflight(declaration, {
      aria2_available: aria2Available,
      queue_readable: true,
      paused: stateBefore.paused,
    });
    await deps.actionLog.record({
      action: "preflight",
      target: "system",
      outcome: result.status === "pass" ? "converged" : "blocked",
      reason: result.status,
      before: { state: stateBefore, queue: summarizeQueue(queueBefore) },
      after: {
        state: await deps.stateStore.load(),
        queue: summarizeQueue(await deps.queueStore.load()),
        preflight: result as unknown as Record<string, unknown>,
      },
      detail: result as unknown as Record<string, unknown>,
    });
    return result;
  });

  app.post("/api/scheduler/resume", async () => {
    const next = await deps.stateStore.update((s) => {
      s.paused = false;
    });
    await deps.actionLog.record({
      action: "resume",
      target: "scheduler",
      outcome: "changed",
      reason: "api_request",
    });
    // BG-25: when the scheduler loop isn't running, /resume must also
    // start it — otherwise unpausing has no effect and queued items sit
    // forever. The dashboard's Start button hits /resume when
    // state.running=false, so this is the path that has to flip the
    // loop on.
    let startResult: { started: boolean; reason: string } | undefined;
    const post = await deps.stateStore.load();
    if (!post.running && deps.startScheduler) {
      try {
        startResult = await deps.startScheduler();
      } catch (err) {
        startResult = {
          started: false,
          reason: err instanceof Error ? err.message : "start_failed",
        };
      }
    }
    return {
      ok: true,
      paused: next.paused,
      _rev: Number(next._rev ?? 0),
      ...(startResult ? { started: startResult.started, start_reason: startResult.reason } : {}),
    };
  });

  // BG-25: explicit start/stop routes. `state.running` means "the
  // scheduler loop is actively dispatching" — both views agree on that
  // definition. /start is idempotent: if running is already true it
  // returns started:false / reason:"already_running" rather than
  // erroring.
  app.post("/api/scheduler/start", async (_req, reply) => {
    if (!deps.startScheduler) {
      return reply
        .code(503)
        .send(errorPayload("scheduler_unavailable", "scheduler lifecycle not wired"));
    }
    const before = await deps.stateStore.load();
    if (before.running) {
      return { ok: true, started: false, reason: "already_running", running: true };
    }
    const result = await deps.startScheduler();
    const after = await deps.stateStore.load();
    await deps.actionLog.record({
      action: "start",
      target: "scheduler",
      outcome: result.started ? "changed" : "unchanged",
      reason: result.reason,
    });
    return {
      ok: true,
      started: result.started,
      reason: result.reason,
      running: Boolean(after.running),
      _rev: Number(after._rev ?? 0),
    };
  });

  app.post("/api/scheduler/stop", async (_req, reply) => {
    if (!deps.stopScheduler) {
      return reply
        .code(503)
        .send(errorPayload("scheduler_unavailable", "scheduler lifecycle not wired"));
    }
    const before = await deps.stateStore.load();
    if (!before.running) {
      return { ok: true, stopped: false, reason: "not_running", running: false };
    }
    const result = await deps.stopScheduler();
    const after = await deps.stateStore.load();
    await deps.actionLog.record({
      action: "stop",
      target: "scheduler",
      outcome: result.stopped ? "changed" : "unchanged",
      reason: result.reason,
    });
    return {
      ok: true,
      stopped: result.stopped,
      reason: result.reason,
      running: Boolean(after.running),
      _rev: Number(after._rev ?? 0),
    };
  });

  app.get("/api/lifecycle", async () => {
    const { existsSync } = await import("node:fs");
    const state = await deps.stateStore.load();

    // BG-20 + BG-27: every component record nests under `result`. BG-27
    // adds three orthogonal axes — `installed` / `current` / `running`
    // (each `bool | null`, with `null` for axes that don't apply) —
    // alongside the BG-20 reason/outcome/message strings. The dashboard
    // can drive headline rendering off the booleans and use the
    // strings for detail rendering.

    const expectedVersion = deps.version ?? "0.0.0";

    // ariaflow-server: we're answering the request, so all three axes
    // are true and the version IS the expected version.
    const ariaflowServer = {
      result: {
        installed: true,
        current: true,
        running: true,
        // BG-29: not on-demand and not externally managed; null = "no opinion".
        expected_running: null,
        managed_by: null,
        reason: "match",
        outcome: "installed · current",
        message: null,
        observation: "ok",
        completion: null,
        version: expectedVersion,
        expected_version: expectedVersion,
      },
    };

    // aria2: split "binary on disk" (installed) from "RPC reachable"
    // (running). `current` only meaningful when installed=true; we
    // don't ship an expected aria2 version so it stays null (true if
    // RPC succeeds, since whatever's there is what we use).
    const aria2BinPath = findAria2c();
    const aria2Installed = Boolean(aria2BinPath);
    let aria2Running = false;
    let aria2Version: string | null = null;
    let aria2Err: string | null = null;
    if (deps.aria2) {
      try {
        const v = await deps.aria2.call<{ version: string }>("aria2.getVersion");
        aria2Running = true;
        aria2Version = v.version;
      } catch (err) {
        aria2Err = err instanceof Error ? err.message : String(err);
      }
    }
    const aria2Current = aria2Installed ? (aria2Running ? true : null) : null;

    // BG-29(a): aria2 is on-demand. expected_running = "would the
    // scheduler want aria2 up right now?" — true while there's work
    // pending or a tick is mid-dispatch. The dashboard's verdict
    // truth-table reads this against `running` to distinguish a
    // healthy idle from a genuine fault.
    const queueItems = await deps.queueStore.load();
    const PENDING = new Set(["queued", "waiting", "active"]);
    const workPending = queueItems.some((i) => PENDING.has(String(i.status ?? "")));
    const aria2ExpectedRunning =
      Boolean(state.running) || Boolean(state.active_gid) || workPending;

    // BG-29(b): managed_by = "who actually spawned the running aria2".
    // We never fork aria2 ourselves today, so the "ariaflow" branch is
    // unreachable in current code; a launchd plist on disk is the only
    // signal we have for "auto-start (launchd)" — anything else is
    // attributed to "external". null when not running.
    const launchdPath =
      `${(await import("node:os")).homedir()}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`;
    const launchdInstalled = existsSync(launchdPath);
    const aria2ManagedBy: "ariaflow" | "launchd" | "external" | null = aria2Running
      ? launchdInstalled
        ? "launchd"
        : "external"
      : null;

    const aria2Result: Record<string, unknown> = {
      installed: aria2Installed,
      current: aria2Current,
      running: aria2Running,
      expected_running: aria2ExpectedRunning,
      managed_by: aria2ManagedBy,
      reason: aria2Running ? "match" : aria2Installed ? "stopped" : "missing",
      outcome: aria2Running
        ? "installed · current"
        : aria2Installed
          ? "stopped"
          : "not installed",
      observation: aria2Running ? "ok" : "failed",
      ...(aria2Version ? { version: aria2Version } : {}),
      ...(aria2BinPath ? { path: aria2BinPath } : {}),
      ...(aria2Err ? { message: aria2Err } : {}),
    };

    // networkquality: system binary, no version policy → current=null.
    // running is derived from "last probe used networkquality recently"
    // — the only honest signal we have without re-running the probe.
    const nq = installNs.networkqualityStatus();
    const probe = (state.last_bandwidth_probe ?? null) as Record<string, unknown> | null;
    const lastProbeAt = Number(state.last_bandwidth_probe_at ?? 0);
    const probeFresh = lastProbeAt > 0 && Date.now() / 1000 - lastProbeAt < 3600;
    const nqRunning = nq.installed
      ? probe?.source === "networkquality" && probeFresh
        ? true
        : null // installed but no recent probe → "unknown", not "stopped"
      : false;
    const networkquality = {
      result: {
        installed: Boolean(nq.installed),
        current: null,
        running: nqRunning,
        // BG-29: on-demand probe, not a daemon — null on both axes.
        expected_running: null,
        managed_by: null,
        reason: nq.reason, // "ready" | "missing"
        outcome: nq.installed && nq.usable ? "installed · usable" : "unavailable",
        observation: nq.installed && nq.usable ? "ok" : "failed",
        message: nq.message,
        ...(nq.command ? { command: nq.command } : {}),
      },
    };

    // aria2-launchd / aria2-systemd: it's a service registration, not
    // an installable binary — installed/current are null. running
    // proxies through aria2's RPC reachability: launchd's job is to
    // keep aria2 up, so if RPC works the unit is doing its job.
    const target = detectServiceTarget();
    const home = (await import("node:os")).homedir();
    const installedPath =
      target === "aria2-launchd"
        ? `${home}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`
        : target === "aria2-systemd"
          ? `${home}/.config/systemd/user/ariaflow-server-aria2.service`
          : null;
    const installedHere = installedPath ? existsSync(installedPath) : false;
    const launchdRunning = installedHere ? aria2Running : false;
    const aria2Launchd = {
      result: {
        installed: null,
        current: null,
        running: launchdRunning,
        // BG-29: informational row — keep `expected_running` null so
        // the dashboard's verdict table treats it as "no opinion"
        // instead of flagging an idle plist as faulty.
        expected_running: null,
        managed_by: installedHere ? "launchd" : null,
        reason: installedHere ? (aria2Running ? "match" : "stopped") : "missing",
        outcome: installedHere
          ? aria2Running
            ? "loaded"
            : "registered · not running"
          : "not installed",
        observation: installedHere && aria2Running ? "ok" : "unknown",
        ...(installedPath ? { path: installedPath } : {}),
      },
    };

    return withMeta("GET", "/api/lifecycle", {
      ok: true,
      "ariaflow-server": ariaflowServer,
      aria2: { result: aria2Result },
      networkquality,
      "aria2-launchd": aria2Launchd,
      session_id: state.session_id,
      session_started_at: state.session_started_at,
      session_last_seen_at: state.session_last_seen_at,
      session_closed_at: state.session_closed_at,
      session_closed_reason: state.session_closed_reason,
    });
  });

  app.post<{ Params: { target: string; action: string }; Querystring: { dry_run?: string } }>(
    "/api/lifecycle/:target/:action",
    async (req, reply) => {
      const target = req.params.target;
      const action = req.params.action;
      const dryRun = req.query?.dry_run === "1" || req.query?.dry_run === "true";

      const ARIA2_SERVICE_TARGETS = new Set([
        "aria2-launchd",
        "aria2-systemd",
        "aria2-service",
      ]);
      const beforeState = await deps.stateStore.load();
      const before = { lifecycle: { state: beforeState } };
      try {
        let result: Record<string, unknown>;
        if (ARIA2_SERVICE_TARGETS.has(target) && action === "install") {
          const out = await installAria2Service({ dryRun });
          result = {
            [out.target]: {
              ok: out.ok,
              commands: out.commands,
              ...(out.results ? { results: out.results } : { dry_run: true }),
            },
          };
        } else if (ARIA2_SERVICE_TARGETS.has(target) && action === "uninstall") {
          const out = await uninstallAria2Service({ dryRun });
          result = {
            [out.target]: {
              ok: out.ok,
              commands: out.commands,
              ...(out.results ? { results: out.results } : { dry_run: true }),
            },
          };
        } else {
          return reply.code(400).send({
            error: "unsupported_action",
            target,
            action,
          });
        }

        await deps.actionLog.record({
          action: "lifecycle_action",
          target: target || "system",
          outcome: "changed",
          reason: action || "lifecycle_action",
          before,
          after: { target, action, result },
          detail: { target, action, dry_run: dryRun, result },
        });
        return { ok: true, target, action, dry_run: dryRun, result };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        await deps.actionLog.record({
          action: "lifecycle_action",
          target: target || "system",
          outcome: "failed",
          reason: "exception",
          before,
          detail: { error: message, target, action, dry_run: dryRun },
        });
        return reply
          .code(500)
          .send(errorPayload("lifecycle_action_failed", message));
      }
    },
  );

  app.post("/api/aria2/multicall", async (req, reply) => {
    if (requireAria2(reply)) return;
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {calls: [{methodName, params?}, ...]}"));
    }
    const rawCalls = (body as { calls?: unknown }).calls;
    if (!Array.isArray(rawCalls) || rawCalls.length === 0) {
      return reply.code(400).send(errorPayload("invalid_calls", "calls must be a non-empty list"));
    }
    const calls: Array<{ methodName: string; params?: unknown[] }> = [];
    for (let i = 0; i < rawCalls.length; i++) {
      const c = rawCalls[i];
      if (!c || typeof c !== "object" || Array.isArray(c)) {
        return reply
          .code(400)
          .send(errorPayload("invalid_call", `calls[${i}] must be an object`, { index: i }));
      }
      const methodName = (c as { methodName?: unknown }).methodName;
      if (typeof methodName !== "string" || !methodName) {
        return reply
          .code(400)
          .send(
            errorPayload("invalid_call", `calls[${i}].methodName must be a non-empty string`, {
              index: i,
            }),
          );
      }
      const params = (c as { params?: unknown }).params;
      if (params !== undefined && !Array.isArray(params)) {
        return reply
          .code(400)
          .send(
            errorPayload("invalid_call", `calls[${i}].params must be an array`, { index: i }),
          );
      }
      calls.push(params !== undefined ? { methodName, params } : { methodName });
    }
    try {
      const results = await aria2.multicall(deps.aria2!, calls);
      return { ok: true, results };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

  app.post("/api/aria2/set_limits", async (req, reply) => {
    if (requireAria2(reply)) return;
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply.code(400).send(errorPayload("invalid_payload", "expected JSON object"));
    }
    const p = body as Record<string, unknown>;
    const gid = typeof p.gid === "string" && p.gid.trim() ? p.gid.trim() : null;
    const applied: Record<string, unknown> = {};
    const errors: string[] = [];

    const num = (v: unknown): number => {
      const n = Number(v);
      return Number.isFinite(n) ? n : NaN;
    };

    const tryRun = async (key: string, fn: () => Promise<unknown>) => {
      try {
        await fn();
        applied[key] = p[key];
      } catch {
        errors.push(key);
      }
    };

    if ("max_overall_download_limit" in p) {
      const v = num(p.max_overall_download_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_overall_download_limit", () =>
          aria2.setMaxOverallDownloadLimit(deps.aria2!, v),
        );
      } else errors.push("max_overall_download_limit");
    }
    if ("max_overall_upload_limit" in p) {
      const v = num(p.max_overall_upload_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_overall_upload_limit", () =>
          aria2.setMaxOverallUploadLimit(deps.aria2!, v),
        );
      } else errors.push("max_overall_upload_limit");
    }
    if ("max_download_limit" in p && gid) {
      const v = num(p.max_download_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_download_limit", () => aria2.setMaxDownloadLimit(deps.aria2!, gid, v));
      } else errors.push("max_download_limit");
    }
    if ("max_upload_limit" in p && gid) {
      const v = num(p.max_upload_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_upload_limit", () => aria2.setMaxUploadLimit(deps.aria2!, gid, v));
      } else errors.push("max_upload_limit");
    }
    if ("seed_ratio" in p) {
      const v = num(p.seed_ratio);
      if (Number.isFinite(v)) {
        await tryRun("seed_ratio", () => aria2.setSeedRatio(deps.aria2!, v));
      } else errors.push("seed_ratio");
    }
    if ("seed_time" in p) {
      const v = num(p.seed_time);
      if (Number.isFinite(v)) {
        await tryRun("seed_time", () => aria2.setSeedTime(deps.aria2!, v));
      } else errors.push("seed_time");
    }

    return { ok: errors.length === 0, applied, errors };
  });

  app.post("/api/aria2/change_option", async (req, reply) => {
    if (requireAria2(reply)) return;
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {gid: string, options: {...}}"));
    }
    const gid = String((body as { gid?: unknown }).gid ?? "").trim();
    const rawOptions = (body as { options?: unknown }).options;
    if (!gid || !rawOptions || typeof rawOptions !== "object" || Array.isArray(rawOptions)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {gid: string, options: {...}}"));
    }
    const options: Record<string, string> = {};
    for (const [k, v] of Object.entries(rawOptions as Record<string, unknown>)) {
      options[k] = String(v);
    }
    try {
      await aria2.changeOption(deps.aria2!, gid, options);
      return { ok: true, gid, applied: options };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

  return app;
}

