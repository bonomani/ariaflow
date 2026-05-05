import type { FastifyInstance } from "fastify";

/**
 * The OpenAPI 3.0 doc shape we surface. After R-J, this is whatever
 * @fastify/swagger produces.
 */
export interface OpenApiDoc {
  openapi: string;
  info: { title: string; version: string; description?: string };
  paths: Record<string, Record<string, unknown>>;
  components?: Record<string, unknown>;
  tags?: Array<{ name: string }>;
}

/**
 * R-J: thin shim around @fastify/swagger's `app.swagger()`. The
 * hand-authored openapi.yaml is retired; the swagger plugin generates
 * the live doc from registered route schemas + the openapi config
 * passed at plugin registration time.
 *
 * Kept as a separate function (rather than calling `app.swagger()`
 * directly at every consumer) so cli/cmdOpenapi and drift.ts stay
 * source-stable across plugin upgrades.
 */
export function generateOpenApi(app: FastifyInstance): OpenApiDoc {
  const swag = app as unknown as { swagger: () => OpenApiDoc };
  if (typeof swag.swagger !== "function") {
    throw new Error(
      "generateOpenApi: app.swagger() not registered — did buildServer skip @fastify/swagger?",
    );
  }
  return swag.swagger();
}
