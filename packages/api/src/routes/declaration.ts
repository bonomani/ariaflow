import type { FastifyReply } from "fastify";
import {
  ACTIONS,
  TARGETS,
  buildTransferSummary,
  errorPayload,
  evaluatePreflight,
  getActiveProgress,
  probeAria2Reachable,
  rankActiveInfos,
  type Declaration,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

export function registerDeclarationRoutes({ app, deps }: RouteContext): void {
  app.get("/api/declaration", async () => {
    const declaration = await deps.declarationStore.load();
    return withMeta("GET", "/api/declaration", { ok: true, declaration });
  });

  app.get("/api/preflight", async () => {
    const declaration = await deps.declarationStore.load();
    const aria2Available = (await probeAria2Reachable(deps.aria2)) === true;
    const state = await deps.stateStore.load();
    const result = evaluatePreflight(declaration, {
      aria2_available: aria2Available,
      queue_readable: true,
      paused: state.paused,
    });
    return { ok: true, ...result };
  });

  app.get("/api/active", async () => {
    const state = await deps.stateStore.load();
    if (!deps.aria2) {
      return { ok: true, active: null, reason: "aria2_unavailable" };
    }
    const progress = await getActiveProgress(deps.aria2, state);
    if (progress) return { ok: true, active: progress };
    // Fall back to picking the best candidate from tellActive
    try {
      const infos = await deps.aria2.call<unknown[]>("aria2.tellActive");
      const ranked = rankActiveInfos(infos as Parameters<typeof rankActiveInfos>[0]);
      if (ranked.length > 0) {
        const top = ranked[0]!;
        return { ok: true, active: buildTransferSummary(top, null, { recovered: true }) };
      }
    } catch {
      /* aria2 unreachable — fall through */
    }
    return { ok: true, active: null };
  });

  const saveDeclaration = async (
    body: unknown,
    reply: FastifyReply,
  ): Promise<unknown> => {
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply.code(400).send(errorPayload("invalid_payload", "expected an object"));
    }
    const incoming = (body as { declaration?: unknown }).declaration ?? body;
    if (!incoming || typeof incoming !== "object" || Array.isArray(incoming)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_declaration", "declaration must be an object"));
    }
    const meta = (incoming as { meta?: unknown }).meta;
    const uic = (incoming as { uic?: unknown }).uic;
    if (
      !meta ||
      typeof meta !== "object" ||
      !uic ||
      typeof uic !== "object" ||
      !Array.isArray((uic as { preferences?: unknown }).preferences) ||
      !Array.isArray((uic as { gates?: unknown }).gates)
    ) {
      return reply
        .code(400)
        .send(errorPayload("invalid_declaration", "missing meta or uic.{gates,preferences}"));
    }
    const saved = await deps.declarationStore.save(incoming as Declaration);
    return { ok: true, declaration: saved };
  };

  app.put("/api/declaration", (req, reply) => saveDeclaration(req.body, reply));

  const patchPreferences = async (
    body: unknown,
    reply: FastifyReply,
  ): Promise<unknown> => {
    if (
      !body ||
      typeof body !== "object" ||
      Array.isArray(body) ||
      Object.keys(body as object).length === 0
    ) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {preference_name: value}"));
    }
    const declaration = await deps.declarationStore.load();
    const preferences = declaration.uic?.preferences ?? [];
    const applied: Record<string, { before: unknown; after: unknown }> = {};
    const unknown: string[] = [];
    for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
      const pref = preferences.find((p) => p.name === key);
      if (!pref) {
        unknown.push(key);
        continue;
      }
      applied[key] = { before: pref.value, after: value };
      pref.value = value;
    }
    if (unknown.length > 0) {
      return reply
        .code(400)
        .send(errorPayload("unknown_preferences", `unknown: ${unknown.join(", ")}`));
    }
    const saved = await deps.declarationStore.save(declaration);
    await deps.actionLog.record({
      action: ACTIONS.declarationPatch,
      target: TARGETS.declaration,
      outcome: "changed",
      reason: "user_patch_preferences",
      after: { applied },
      detail: { applied },
    });
    return { ok: true, applied, declaration: saved };
  };

  app.patch("/api/declaration/preferences", (req, reply) => patchPreferences(req.body, reply));
}
