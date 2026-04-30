import type { FastifyInstance } from "fastify";

interface OpenApiPathItem {
  [method: string]: { tags: string[]; summary: string; responses: Record<string, unknown> };
}

export interface OpenApiDoc {
  openapi: "3.0.3";
  info: { title: string; version: string };
  tags: { name: string }[];
  paths: Record<string, OpenApiPathItem>;
}

const TAG_MAP: Array<[string, string]> = [
  ["/api/downloads", "Queue"],
  ["/api/scheduler", "Scheduler"],
  ["/api/declaration", "Config"],
  ["/api/aria2", "aria2"],
  ["/api/bandwidth", "Bandwidth"],
  ["/api/torrents", "Torrents"],
  ["/api/sessions", "Sessions"],
  ["/api/lifecycle", "Lifecycle"],
  ["/api/log", "Observability"],
  ["/api/events", "Observability"],
  ["/api/health", "Observability"],
  ["/api/status", "Queue"],
  ["/api/actions", "Observability"],
  ["/api/preflight", "Config"],
  ["/api/active", "Queue"],
  ["/api/docs", "Meta"],
  ["/api/openapi", "Meta"],
  ["/api", "Meta"],
];

const sortedTagMap = [...TAG_MAP].sort((a, b) => b[0].length - a[0].length);

function tagForPath(path: string): string {
  for (const [prefix, tag] of sortedTagMap) {
    if (path.startsWith(prefix)) return tag;
  }
  return "Other";
}

const DEFAULT_RESPONSE = { "200": { description: "OK" } };

/**
 * Convert Fastify's `:id` path syntax to OpenAPI's `{id}` form.
 */
const toOpenApiPath = (p: string): string => p.replace(/:([A-Za-z_][\w]*)/g, "{$1}");

/**
 * Walk a Fastify instance's registered routes and emit a minimal
 * OpenAPI 3.0 doc. Paths are tagged via TAG_MAP (longest-prefix wins).
 *
 * This is intentionally schema-light — body/response schemas are out
 * of scope here; Phase 14 already validates request bodies in code.
 * The output is suitable as a seed for `openapi.yaml` and for the
 * drift-check workflow that compares declared paths to the live server.
 */
export function generateOpenApi(
  app: FastifyInstance,
  info: { title?: string; version?: string } = {},
): OpenApiDoc {
  const paths: Record<string, OpenApiPathItem> = {};
  const tags = new Set<string>();
  // buildServer() attaches an onRoute hook that records every full
  // registered URL; prefer that list when present (it's accurate) and
  // fall back to parsing printRoutes() for instances built without it.
  type Route = { method: string | string[]; url: string };
  const routes =
    (app as unknown as { _ariaflowRoutes?: Route[] })._ariaflowRoutes ?? collectRoutes(app);
  // Optional override map for routes whose Fastify path template doesn't
  // match the canonical OpenAPI shape (e.g. /api/torrents/:file should
  // emit /api/torrents/{infohash}.torrent).
  const overrides =
    (app as unknown as { _ariaflowOpenApiPathOverrides?: Map<string, string> })
      ._ariaflowOpenApiPathOverrides ?? new Map<string, string>();
  for (const route of routes) {
    const url = overrides.get(route.url) ?? toOpenApiPath(route.url);
    const methods = Array.isArray(route.method) ? route.method : [route.method];
    for (const method of methods) {
      const m = method.toLowerCase();
      const tag = tagForPath(route.url);
      tags.add(tag);
      paths[url] ??= {};
      paths[url][m] = {
        tags: [tag],
        summary: `${method.toUpperCase()} ${url}`,
        responses: { ...DEFAULT_RESPONSE },
      };
    }
  }
  return {
    openapi: "3.0.3",
    info: { title: info.title ?? "ariaflow-server", version: info.version ?? "0.0.0" },
    tags: [...tags].sort().map((name) => ({ name })),
    paths,
  };
}

function collectRoutes(app: FastifyInstance): Array<{ method: string | string[]; url: string }> {
  // Fall back to parsing printRoutes() text output. Format:
  //   └── (api) (GET, POST, HEAD)
  //       └── /downloads (GET, POST)
  // To avoid relying on the printer's tree shape, just call
  // app.printRoutes({commonPrefix: false}) and split on the rule.
  const text = app.printRoutes({ commonPrefix: false });
  const out: Array<{ method: string | string[]; url: string }> = [];
  const re = /(\/\S*)\s+\(([A-Z, ]+)\)/g;
  for (const m of text.matchAll(re)) {
    out.push({ url: m[1]!, method: m[2]!.split(",").map((s) => s.trim()) });
  }
  return out;
}
