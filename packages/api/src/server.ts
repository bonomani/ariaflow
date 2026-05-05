import Fastify, { type FastifyInstance } from "fastify";
import fastifyCors from "@fastify/cors";
import { errorPayload } from "@ariaflow/core";
import type {
  ActionLog,
  ArchiveStore,
  Aria2Client,
  DeclarationStore,
  EventBus,
  PeerRegistry,
  QueueOps,
  QueueStore,
  SessionService,
  StateStore,
} from "@ariaflow/core";
import { registerDefaultFreshness } from "./freshness.js";
import { ERRORS_RECENT_MAX, type ServerMetrics, type RouteContext } from "./routes/_context.js";
import { registerMetaRoutes } from "./routes/meta.js";
import { registerLogRoutes } from "./routes/log.js";
import { registerSessionRoutes } from "./routes/sessions.js";
import { registerPeersRoutes } from "./routes/peers.js";
import { registerEventsRoutes } from "./routes/events.js";
import { registerStatusRoute } from "./routes/status.js";
import { registerDownloadsRoutes } from "./routes/downloads.js";
import { registerDeclarationRoutes } from "./routes/declaration.js";
import { registerBandwidthRoutes } from "./routes/bandwidth.js";
import { registerAria2Routes } from "./routes/aria2.js";
import { registerTorrentsRoutes } from "./routes/torrents.js";
import { registerSchedulerRoutes } from "./routes/scheduler.js";
import { registerLifecycleRoutes } from "./routes/lifecycle.js";

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

/**
 * Build a Fastify instance wired with the migrated routes. The caller
 * owns the storage stack (lock, stores, ops) and passes it in — keeps
 * this layer free of singletons and easy to unit-test.
 *
 * Routes live under `routes/`, one file per group. This file's job is
 * the cross-cutting wiring: CORS, hooks, metrics, freshness registry,
 * and registering each group on the Fastify instance.
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
  const metrics: ServerMetrics = {
    startedAt: Date.now(),
    requestsTotal: 0,
    errorsTotal: 0,
    sseClients: 0,
    bytesReceivedTotal: 0,
    bytesSentTotal: 0,
    errorsRecent: [],
  };
  app.addHook("onRequest", async (req) => {
    metrics.requestsTotal += 1;
    const len = Number(req.headers["content-length"] ?? 0);
    if (Number.isFinite(len) && len > 0) metrics.bytesReceivedTotal += len;
  });
  app.addHook("onResponse", async (req, reply) => {
    if (reply.statusCode >= 400) {
      metrics.errorsTotal += 1;
      // BG-42: ring buffer of recent failures so the dashboard's
      // Errors chip can drill down. routerPath is the matched route
      // (e.g. "/api/downloads/:id") when available; falls back to the
      // raw URL.
      metrics.errorsRecent.push({
        at: Math.round(Date.now() / 1000),
        method: req.method,
        path: (req as unknown as { routerPath?: string }).routerPath ?? req.url,
        status: reply.statusCode,
      });
      if (metrics.errorsRecent.length > ERRORS_RECENT_MAX) {
        metrics.errorsRecent.splice(
          0,
          metrics.errorsRecent.length - ERRORS_RECENT_MAX,
        );
      }
    }
    const sent = Number(reply.getHeader("content-length") ?? 0);
    if (Number.isFinite(sent) && sent > 0) metrics.bytesSentTotal += sent;
  });

  if (deps.eventBus) {
    deps.actionLog.setBus(deps.eventBus);
    deps.sessionService.setBus(deps.eventBus);
    // R-T: state mutations publish state_changed so /api/events SSE
    // clients see scheduler/run/pause flips live, matching the
    // freshness contract's claim that /api/status is "live, sse,
    // transport_topics: [items, scheduler]".
    deps.stateStore.setBus(deps.eventBus);
  }

  app.setNotFoundHandler((_req, reply) => {
    reply.code(404).send(errorPayload("not_found", "resource not found"));
  });

  const ctx: RouteContext = { app, deps, metrics };

  registerMetaRoutes(ctx);
  registerLogRoutes(ctx);
  registerSessionRoutes(ctx);
  registerPeersRoutes(ctx);
  registerEventsRoutes(ctx);
  registerStatusRoute(ctx);
  registerDownloadsRoutes(ctx);
  registerDeclarationRoutes(ctx);
  registerBandwidthRoutes(ctx);
  registerAria2Routes(ctx);
  registerTorrentsRoutes(ctx);
  registerSchedulerRoutes(ctx);
  registerLifecycleRoutes(ctx);

  return app;
}
