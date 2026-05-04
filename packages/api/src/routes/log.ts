import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

export function registerLogRoutes({ app, deps }: RouteContext): void {
  app.get<{ Querystring: { limit?: string } }>("/api/actions", async (req) => {
    const limitRaw = req.query?.limit;
    const limit = Math.min(Math.max(Number(limitRaw) || 200, 1), 5000);
    const entries = await deps.actionLog.load(limit);
    return { ok: true, limit, entries };
  });

  // /api/log returns a clamped tail of actions.jsonl in {items} shape.
  // Default limit 120, max 500.
  // BG-24 cosmetic nit: emit `ok: true` so the response is consistent
  // with every other backend endpoint (frontend gate is
  // `data?.ok !== false` so the missing-key form was working, but the
  // shape was inconsistent).
  app.get<{ Querystring: { limit?: string } }>("/api/log", async (req) => {
    const limitRaw = req.query?.limit;
    let limit = 120;
    const n = Number(limitRaw);
    if (Number.isFinite(n)) limit = Math.max(1, Math.min(500, Math.trunc(n)));
    const items = await deps.actionLog.load(limit);
    return withMeta("GET", "/api/log", { ok: true, items });
  });
}
