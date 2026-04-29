import Fastify, { type FastifyInstance } from "fastify";
import {
  ActionLog,
  allowedActions,
  aria2,
  Aria2Client,
  bandwidthConfigFrom,
  buildTransferSummary,
  DeclarationStore,
  errorPayload,
  EventBus,
  evaluatePreflight,
  getActiveProgress,
  MANAGED_ARIA2_OPTIONS,
  parseAddItems,
  QueueStore,
  rankActiveInfos,
  SAFE_ARIA2_OPTIONS,
  SessionService,
  StateStore,
  summarizeQueue,
  validateChangeOptions,
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
  /** Optional version string surfaced at /api/version (default "0.0.0"). */
  version?: string;
  /** Optional EventBus; if provided, /api/events streams its publish() calls. */
  eventBus?: EventBus;
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

  // Capture full registered URLs for the OpenAPI introspector. Fastify's
  // printRoutes() formats output as a tree with relative leaf segments
  // that's awkward to parse; the onRoute hook fires once per route with
  // the full url, so we just record them here.
  const recorded: Array<{ method: string | string[]; url: string }> = [];
  (app as unknown as { _ariaflowRoutes: typeof recorded })._ariaflowRoutes = recorded;
  app.addHook("onRoute", (route) => {
    recorded.push({ method: route.method, url: route.url });
  });

  if (deps.eventBus) {
    deps.actionLog.setBus(deps.eventBus);
    deps.sessionService.setBus(deps.eventBus);
  }

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

  app.post<{ Params: { id: string } }>("/api/downloads/:id/pause", async (req, reply) => {
    if (!validateItemId(req.params.id)) {
      return reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
    }
    const next = await deps.queueOps.transitionStatus(req.params.id, "paused", "paused_at");
    if (!next) return reply.code(404).send(errorPayload("not_found", "item not found"));
    return { ok: true, item: next };
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

  // /api/log mirrors the Python route's {items} shape — a clamped tail
  // of actions.jsonl. Default limit 120, max 500 (matches Python).
  app.get<{ Querystring: { limit?: string } }>("/api/log", async (req) => {
    const limitRaw = req.query?.limit;
    let limit = 120;
    const n = Number(limitRaw);
    if (Number.isFinite(n)) limit = Math.max(1, Math.min(500, Math.trunc(n)));
    const items = await deps.actionLog.load(limit);
    return { items };
  });

  app.get("/api/health", async () => {
    return { ok: true, status: "healthy", uptime_seconds: Math.round(process.uptime()) };
  });

  app.get("/api/version", async () => {
    return { ok: true, version: deps.version ?? "0.0.0" };
  });

  app.get("/api/openapi", async () => {
    const { generateOpenApi } = await import("./openapi.js");
    return generateOpenApi(app);
  });

  app.get("/api/events", async (req, reply) => {
    const bus = deps.eventBus;
    if (!bus) {
      return reply.code(503).send(errorPayload("events_unavailable", "no event bus wired"));
    }
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    reply.raw.write(`: connected\n\n`);
    let alive = true;
    const writeEvent = (event: string, data: unknown) => {
      if (!alive) return;
      reply.raw.write(`event: ${event}\n`);
      reply.raw.write(`data: ${JSON.stringify(data)}\n\n`);
    };
    const unsubscribe = bus.subscribe(writeEvent);
    const heartbeat = setInterval(() => {
      if (alive) reply.raw.write(`: ping\n\n`);
    }, 15_000);
    const cleanup = () => {
      alive = false;
      clearInterval(heartbeat);
      unsubscribe();
    };
    req.raw.on("close", cleanup);
    reply.raw.on("close", cleanup);
    // Keep the response open — Fastify will resolve once we return,
    // but the underlying socket stays alive thanks to the listeners.
    return reply;
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

  app.get("/api/aria2/global_option", async (_req, reply) => {
    if (requireAria2(reply)) return;
    try {
      const opts = await aria2.getGlobalOption(deps.aria2!);
      return { ok: true, options: opts };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

  app.get<{ Querystring: { gid?: string } }>("/api/aria2/option", async (req, reply) => {
    if (requireAria2(reply)) return;
    const gid = (req.query?.gid ?? "").trim();
    if (!gid) {
      return reply.code(400).send(errorPayload("missing_gid", "gid query parameter required"));
    }
    try {
      const opts = await aria2.getOption(deps.aria2!, gid);
      return { ok: true, gid, options: opts };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

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
    return { ok: true, paused: next.paused, _rev: Number(next._rev ?? 0) };
  });

  app.get("/api/lifecycle", async () => {
    const core = await import("@ariaflow/core");
    const state = await deps.stateStore.load();
    return {
      ok: true,
      // Lightweight status_all() equivalent — the install-side checks
      // (brew, aria2 service) are deferred to a service-layer port.
      ariaflow_server: {
        installed: true,
        version: deps.version ?? "0.0.0",
      },
      networkquality: core.install.networkqualityStatus(),
      session_id: state.session_id,
      session_started_at: state.session_started_at,
      session_last_seen_at: state.session_last_seen_at,
      session_closed_at: state.session_closed_at,
      session_closed_reason: state.session_closed_reason,
    };
  });

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
