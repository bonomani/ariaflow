import { errorPayload, toWireState } from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

export function registerSessionRoutes({ app, deps }: RouteContext): void {
  app.get("/api/sessions/current", async () => {
    const state = await deps.stateStore.load();
    if (!state.session_id) {
      return withMeta("GET", "/api/sessions/current", { ok: true, session: null });
    }
    const stats = await deps.sessionService.stats();
    return withMeta("GET", "/api/sessions/current", { ok: true, session: toWireState(state), stats });
  });

  // openapi.yaml documents /api/sessions (= current session) and
  // /api/sessions/stats as separate endpoints; both are thin views
  // over SessionService and used by the dashboard.
  app.get("/api/sessions", async () => {
    const state = await deps.stateStore.load();
    return withMeta("GET", "/api/sessions", {
      ok: true,
      session: state.session_id ? toWireState(state) : null,
    });
  });

  app.get("/api/sessions/stats", async () => {
    const stats = await deps.sessionService.stats();
    return withMeta("GET", "/api/sessions/stats", { ok: true, stats });
  });

  app.post("/api/sessions/start", async () => {
    const next = await deps.sessionService.startNew("api_request");
    return { ok: true, session: toWireState(next) };
  });

  app.post("/api/sessions/close", async (_req, reply) => {
    try {
      const closed = await deps.sessionService.close("api_request");
      return { ok: true, session: toWireState(closed) };
    } catch (err) {
      const msg = err instanceof Error ? err.message : "close failed";
      return reply.code(409).send(errorPayload("session_close_blocked", msg));
    }
  });

  app.get("/api/sessions/history", async () => {
    return withMeta("GET", "/api/sessions/history", {
      ok: true,
      history: await deps.sessionService.loadHistory(),
    });
  });
}
