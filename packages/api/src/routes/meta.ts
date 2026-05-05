import { stringify as yamlStringify } from "yaml";
import { listFreshness, withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

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

export function registerMetaRoutes({ app, deps }: RouteContext): void {
  // BG-42: silence /favicon.ico. Browsers that hit the backend origin
  // directly (Swagger UI, "open in browser" etc.) auto-fetch this and
  // get a 404 otherwise — each one inflates health.errors_total without
  // representing anything operationally interesting. Returning 204
  // matches what the dashboard already does in webapp.py.
  app.get("/favicon.ico", async (_req, reply) => {
    reply.code(204);
    return reply.send();
  });

  // Stub /api/tests so the documented endpoint exists. In-server test
  // execution is intentionally out of scope; users run `pnpm test` on
  // the host.
  app.get("/api/tests", async () => ({
    ok: true,
    available: false,
    message: "use 'pnpm test' on the host; in-server test execution is not implemented",
  }));

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

  // R-J: openapi.yaml is now generated from the registered route
  // schemas by @fastify/swagger (see server.ts). The hand-authored
  // openapi.yaml file is retired; this serializes the live doc to YAML
  // on demand. BG-37 (info.version stamping) is preserved by passing
  // deps.version into swagger's openapi.info at registration time.
  app.get("/api/openapi.yaml", async (_req, reply) => {
    reply.type("application/yaml");
    const doc = (app as unknown as { swagger: () => Record<string, unknown> }).swagger();
    return reply.send(yamlStringify(doc));
  });

  app.get("/api/docs", async (_req, reply) => {
    reply.type("text/html; charset=utf-8");
    return reply.send(SWAGGER_UI_HTML);
  });

  app.get("/api/openapi", async () => {
    return (app as unknown as { swagger: () => Record<string, unknown> }).swagger();
  });
}
