import type { FastifyInstance, FastifyReply } from "fastify";
import { errorPayload } from "@ariaflow/core";
import type { ServerDeps } from "../server.js";

export interface ServerMetrics {
  startedAt: number;
  requestsTotal: number;
  errorsTotal: number;
  sseClients: number;
  bytesReceivedTotal: number;
  bytesSentTotal: number;
}

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
