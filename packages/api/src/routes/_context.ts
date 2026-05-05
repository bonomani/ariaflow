import type { FastifyInstance, FastifyReply } from "fastify";
import { errorPayload, validateItemId } from "@ariaflow/core";
import type { ServerDeps } from "../server.js";

/**
 * BG-42: ring-buffer entry summarizing one 4xx/5xx response. Surfaces
 * on /api/health.errors_recent + /api/status.health.errors_recent so
 * the dashboard's Errors chip can drill down into recent failures
 * instead of just showing a count.
 */
export interface RecentError {
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
