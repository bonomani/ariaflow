// BG-31: per-endpoint freshness contract.
//
// Single registry mapping `${METHOD} ${path}` → freshness class + extras.
// `withMeta(key, body)` stamps the body with the registered block; the
// same registry is exposed verbatim by `GET /api/_meta`. Two declarations
// of the same fact would defeat the point — callers must not hand-write
// inline `meta` objects.
//
// Vocabulary (see docs/FRESHNESS.md):
//   bootstrap  — fetch once per session, then cache
//   live       — server pushes (SSE); client follows the push
//   warm       — short TTL, refetch on demand
//   cold       — rarely changes, refetch only on user action
//   on-action  — only refetch after a specific mutation
//   swr        — stale-while-revalidate; show cached, refetch in bg
//   derived    — computed from another endpoint's body, never fetched

type FreshnessClass =
  | "bootstrap"
  | "live"
  | "warm"
  | "cold"
  | "on-action"
  | "swr"
  | "derived";

interface FreshnessMeta {
  freshness: FreshnessClass;
  /** Required for `warm` / `swr`. */
  ttl_s?: number;
  /** Required for `on-action`. List of `${METHOD} ${path}` triggers. */
  revalidate_on?: string[];
  /** Required for `live`. Today only "sse". */
  transport?: "sse";
  /**
   * BG-32: SSE topic(s) that carry updates for this endpoint. Surfaces
   * in /api/_meta so the dashboard's FreshnessRouter knows which
   * `?topics=` to subscribe with. Only meaningful for `live` entries.
   */
  transport_topics?: string[];
}

/** Frozen lookup: `${METHOD} ${path}` → meta. */
const REGISTRY = new Map<string, FreshnessMeta>();

const norm = (method: string, path: string): string => `${method.toUpperCase()} ${path}`;

export function registerFreshness(method: string, path: string, meta: FreshnessMeta): void {
  validateMeta(meta);
  REGISTRY.set(norm(method, path), meta);
}

export function getFreshness(method: string, path: string): FreshnessMeta | undefined {
  return REGISTRY.get(norm(method, path));
}

export function listFreshness(): Array<{ method: string; path: string } & FreshnessMeta> {
  const out: Array<{ method: string; path: string } & FreshnessMeta> = [];
  for (const [key, meta] of REGISTRY) {
    const sp = key.indexOf(" ");
    out.push({ method: key.slice(0, sp), path: key.slice(sp + 1), ...meta });
  }
  out.sort((a, b) => (a.path === b.path ? a.method.localeCompare(b.method) : a.path.localeCompare(b.path)));
  return out;
}

/** Stamp `meta` onto a payload using the registry. Throws if unknown. */
export function withMeta<T extends Record<string, unknown>>(
  method: string,
  path: string,
  body: T,
): T & { meta: FreshnessMeta } {
  const meta = getFreshness(method, path);
  if (!meta) throw new Error(`freshness: no registry entry for ${norm(method, path)}`);
  return { ...body, meta };
}

function validateMeta(meta: FreshnessMeta): void {
  if (meta.freshness === "warm" || meta.freshness === "swr") {
    if (typeof meta.ttl_s !== "number" || meta.ttl_s <= 0) {
      throw new Error(`freshness: ${meta.freshness} requires ttl_s > 0`);
    }
  }
  if (meta.freshness === "on-action") {
    if (!meta.revalidate_on || meta.revalidate_on.length === 0) {
      throw new Error(`freshness: on-action requires revalidate_on`);
    }
  }
  if (meta.freshness === "live" && meta.transport !== "sse") {
    throw new Error(`freshness: live requires transport="sse"`);
  }
}

/** Reset the registry. Tests only. */
export function _resetFreshness(): void {
  REGISTRY.clear();
}

/**
 * Initial coverage per BG-31 #4. Called once during buildServer; safe to
 * call multiple times (idempotent — same key overwrites).
 */
export function registerDefaultFreshness(): void {
  registerFreshness("GET", "/api/status", {
    freshness: "live",
    transport: "sse",
    transport_topics: ["items", "scheduler"],
  });
  registerFreshness("GET", "/api/lifecycle", {
    freshness: "warm",
    ttl_s: 30,
    revalidate_on: [
      "POST /api/lifecycle/:target/:action",
    ],
  });
  registerFreshness("GET", "/api/bandwidth", {
    freshness: "on-action",
    revalidate_on: ["POST /api/bandwidth/probe"],
  });
  registerFreshness("GET", "/api/aria2/global_option", { freshness: "cold" });
  registerFreshness("GET", "/api/aria2/option_tiers", { freshness: "cold" });
  registerFreshness("GET", "/api/active", {
    freshness: "live",
    transport: "sse",
    transport_topics: ["items", "scheduler"],
  });
  registerFreshness("GET", "/api/preflight", {
    freshness: "on-action",
    revalidate_on: [
      "PUT /api/declaration",
      "PATCH /api/declaration/preferences",
      "POST /api/scheduler/start",
      "POST /api/scheduler/pause",
      "POST /api/scheduler/resume",
    ],
  });
  registerFreshness("GET", "/api/sessions/current", { freshness: "swr", ttl_s: 30 });
  registerFreshness("GET", "/api/sessions/stats", { freshness: "swr", ttl_s: 30 });
  registerFreshness("GET", "/api/log", { freshness: "swr", ttl_s: 10 });
  // BG-34: per-tab loader endpoints. Classes follow the frontend's
  // suggestions (see docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md). Choice
  // isn't load-bearing — the FreshnessRouter just needs *some* class.
  registerFreshness("GET", "/api/downloads", { freshness: "warm", ttl_s: 15 });
  registerFreshness("GET", "/api/torrents", { freshness: "warm", ttl_s: 30 });
  registerFreshness("GET", "/api/peers", { freshness: "warm", ttl_s: 30 });
  registerFreshness("GET", "/api/downloads/archive", { freshness: "swr", ttl_s: 60 });
  registerFreshness("GET", "/api/sessions", { freshness: "swr", ttl_s: 30 });
  registerFreshness("GET", "/api/sessions/history", { freshness: "swr", ttl_s: 30 });
  // BG-40: /api/scheduler is the snapshot view of state.scheduler_status
  // + wait_reason. The same fields flow on /api/status via the
  // "scheduler" SSE topic; this endpoint is the cold-cache fallback.
  registerFreshness("GET", "/api/scheduler", { freshness: "swr", ttl_s: 5 });
  registerFreshness("GET", "/api/declaration", {
    freshness: "cold",
    revalidate_on: [
      "PUT /api/declaration",
      "PATCH /api/declaration/preferences",
    ],
  });
  registerFreshness("GET", "/api/health", { freshness: "bootstrap" });
  registerFreshness("GET", "/api/version", { freshness: "bootstrap" });
  registerFreshness("GET", "/api/_meta", { freshness: "bootstrap" });
}
