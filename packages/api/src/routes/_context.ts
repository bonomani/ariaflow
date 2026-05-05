import type { FastifyInstance, FastifyReply } from "fastify";
import { errorPayload, validateItemId, type QueueItemRecord } from "@ariaflow/core";
import type { ServerDeps } from "../server.js";

/**
 * BG-42: ring-buffer entry summarizing one 4xx/5xx response. Surfaces
 * on /api/health.errors_recent + /api/status.health.errors_recent so
 * the dashboard's Errors chip can drill down into recent failures
 * instead of just showing a count.
 */
interface RecentError {
  /** Epoch seconds when the response went out. */
  at: number;
  method: string;
  /** Matched route URL when available; otherwise raw req.url. */
  path: string;
  status: number;
}

export interface ServerMetrics {
  startedAt: number;
  requestsTotal: number;
  errorsTotal: number;
  sseClients: number;
  bytesReceivedTotal: number;
  bytesSentTotal: number;
  /** BG-42: ring buffer of the last N error responses. */
  errorsRecent: RecentError[];
}

/** BG-42: how many recent-error entries to retain. */
export const ERRORS_RECENT_MAX = 20;

export interface RouteContext {
  app: FastifyInstance;
  deps: ServerDeps;
  metrics: ServerMetrics;
}

/**
 * Factory for the requireAria2 guard used by /api/aria2/* and a handful
 * of other RPC-coupled routes. Returns null when aria2 is wired (proceed)
 * or the reply (already sent 503) when not.
 */
export const requireAria2Of =
  (deps: ServerDeps) =>
  (reply: FastifyReply): FastifyReply | null => {
    if (deps.aria2) return null;
    reply.code(503).send(errorPayload("aria2_unavailable", "no aria2 client wired"));
    return reply;
  };

/**
 * Reject :id params that aren't a valid UUID before the handler runs.
 * Returns the validated id on success, or null after sending a 400
 * envelope. Caller must `return` immediately on null.
 */
export function validateIdParam(id: string, reply: FastifyReply): string | null {
  if (validateItemId(id)) return id;
  reply.code(400).send(errorPayload("invalid_id", "item id must be a UUID"));
  return null;
}

/**
 * Send a 502 `rpc_error` envelope from a caught aria2 RPC exception.
 * Returns the reply so callers can `return sendRpcError(reply, err)`.
 */
export function sendRpcError(reply: FastifyReply, err: unknown): FastifyReply {
  return reply
    .code(502)
    .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
}

/**
 * Send a 404 `not_found` envelope for a missing queue item. Returns
 * the reply so callers can `return sendNotFound(reply)`.
 */
export function sendNotFound(reply: FastifyReply, message = "item not found"): FastifyReply {
  return reply.code(404).send(errorPayload("not_found", message));
}

/**
 * Validate the :id param, load the queue, and resolve the matching item.
 * On any failure (bad UUID, item missing) the 400/404 envelope is sent
 * and the helper returns null. Caller still gets `items` so it can save
 * back after mutating the row.
 */
export async function loadItemOr404(
  deps: ServerDeps,
  id: string,
  reply: FastifyReply,
): Promise<{ items: QueueItemRecord[]; item: QueueItemRecord } | null> {
  if (!validateIdParam(id, reply)) return null;
  const items = await deps.queueStore.load();
  const item = items.find((i) => i.id === id);
  if (!item) {
    sendNotFound(reply);
    return null;
  }
  return { items, item };
}

/**
 * Coerce a request body into a plain object record, or send a 400
 * `invalid_payload` envelope and return null. Centralizes the
 * `!body || typeof body !== "object" || Array.isArray(body)` pattern
 * that was duplicated across six routes.
 */
export function requireObjectBody(
  body: unknown,
  reply: FastifyReply,
  expected = "expected JSON object",
): Record<string, unknown> | null {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    reply.code(400).send(errorPayload("invalid_payload", expected));
    return null;
  }
  return body as Record<string, unknown>;
}
