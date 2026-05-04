import { errorPayload } from "@ariaflow/core";
import { eventMatchesTopics, parseTopics } from "../event-topics.js";
import type { RouteContext } from "./_context.js";

export function registerEventsRoutes({ app, deps, metrics }: RouteContext): void {
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
}
