import type { FastifyReply, FastifyRequest } from "fastify";
import {
  ACTIONS,
  TARGETS,
  aria2,
  errorPayload,
  MANAGED_ARIA2_OPTIONS,
  SAFE_ARIA2_OPTIONS,
  validateChangeOptions,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import { requireAria2Of, type RouteContext } from "./_context.js";

export function registerAria2Routes({ app, deps }: RouteContext): void {
  const requireAria2 = requireAria2Of(deps);

  app.get("/api/aria2/option_tiers", async () => {
    const declaration = await deps.declarationStore.load();
    const unsafe = declaration.uic.preferences.find((p) => p.name === "aria2_unsafe_options");
    return withMeta("GET", "/api/aria2/option_tiers", {
      ok: true,
      managed: [...MANAGED_ARIA2_OPTIONS].sort(),
      safe: [...SAFE_ARIA2_OPTIONS].sort(),
      unsafe_enabled: Boolean(unsafe?.value),
    });
  });

  // BG-22: the dashboard reads `aria2Options[opt]` straight from the
  // response body (`this.aria2Options = data`), so the options dict
  // must be spread at the top level. aria2 option names are kebab-case
  // ("connect-timeout", "max-tries", ...) so they never collide with
  // our envelope keys (`ok`, `gid`).
  const globalOptionsHandler = async (
    _req: FastifyRequest,
    reply: FastifyReply,
  ) => {
    if (requireAria2(reply)) return;
    try {
      const opts = await aria2.getGlobalOption(deps.aria2!);
      return withMeta("GET", "/api/aria2/global_option", { ok: true, ...opts });
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  };

  const itemOptionsHandler = async (
    req: FastifyRequest<{ Querystring: { gid?: string } }>,
    reply: FastifyReply,
  ) => {
    if (requireAria2(reply)) return;
    const gid = (req.query?.gid ?? "").trim();
    if (!gid) {
      return reply.code(400).send(errorPayload("missing_gid", "gid query parameter required"));
    }
    try {
      const opts = await aria2.getOption(deps.aria2!, gid);
      return { ok: true, gid, ...opts };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  };

  app.get("/api/aria2/global_option", globalOptionsHandler);
  app.get<{ Querystring: { gid?: string } }>("/api/aria2/option", itemOptionsHandler);

  app.post("/api/aria2/change_global_option", async (req, reply) => {
    if (requireAria2(reply)) return;
    const declaration = await deps.declarationStore.load();
    const validated = validateChangeOptions(req.body, declaration);
    if (!validated.ok) {
      return reply.code(400).send(errorPayload(validated.error, validated.message));
    }
    try {
      const before = await aria2.getGlobalOption(deps.aria2!);
      await aria2.changeGlobalOption(deps.aria2!, validated.options);
      const after = await aria2.getGlobalOption(deps.aria2!);
      await deps.actionLog.record({
        action: ACTIONS.aria2ChangeOptions,
        target: TARGETS.aria2,
        outcome: "changed",
        reason: "user_change_options",
        before: { options: before },
        after: { options: after },
      });
      return { ok: true, applied: validated.options };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

  app.post("/api/aria2/multicall", async (req, reply) => {
    if (requireAria2(reply)) return;
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {calls: [{methodName, params?}, ...]}"));
    }
    const rawCalls = (body as { calls?: unknown }).calls;
    if (!Array.isArray(rawCalls) || rawCalls.length === 0) {
      return reply.code(400).send(errorPayload("invalid_calls", "calls must be a non-empty list"));
    }
    const calls: Array<{ methodName: string; params?: unknown[] }> = [];
    for (let i = 0; i < rawCalls.length; i++) {
      const c = rawCalls[i];
      if (!c || typeof c !== "object" || Array.isArray(c)) {
        return reply
          .code(400)
          .send(errorPayload("invalid_call", `calls[${i}] must be an object`, { index: i }));
      }
      const methodName = (c as { methodName?: unknown }).methodName;
      if (typeof methodName !== "string" || !methodName) {
        return reply
          .code(400)
          .send(
            errorPayload("invalid_call", `calls[${i}].methodName must be a non-empty string`, {
              index: i,
            }),
          );
      }
      const params = (c as { params?: unknown }).params;
      if (params !== undefined && !Array.isArray(params)) {
        return reply
          .code(400)
          .send(
            errorPayload("invalid_call", `calls[${i}].params must be an array`, { index: i }),
          );
      }
      calls.push(params !== undefined ? { methodName, params } : { methodName });
    }
    try {
      const results = await aria2.multicall(deps.aria2!, calls);
      return { ok: true, results };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });

  app.post("/api/aria2/set_limits", async (req, reply) => {
    if (requireAria2(reply)) return;
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply.code(400).send(errorPayload("invalid_payload", "expected JSON object"));
    }
    const p = body as Record<string, unknown>;
    const gid = typeof p.gid === "string" && p.gid.trim() ? p.gid.trim() : null;

    // Declarative table: each entry is one acceptable field on the
    // request body. `requiresGid: true` means the field is silently
    // ignored when no gid is provided (per-item limits need a target).
    type LimitEntry = {
      key: string;
      requiresGid?: boolean;
      apply: (value: number) => Promise<unknown>;
    };
    const a = deps.aria2!;
    const limits: readonly LimitEntry[] = [
      { key: "max_overall_download_limit", apply: (v) => aria2.setMaxOverallDownloadLimit(a, v) },
      { key: "max_overall_upload_limit", apply: (v) => aria2.setMaxOverallUploadLimit(a, v) },
      { key: "max_download_limit", requiresGid: true, apply: (v) => aria2.setMaxDownloadLimit(a, gid!, v) },
      { key: "max_upload_limit", requiresGid: true, apply: (v) => aria2.setMaxUploadLimit(a, gid!, v) },
      { key: "seed_ratio", apply: (v) => aria2.setSeedRatio(a, v) },
      { key: "seed_time", apply: (v) => aria2.setSeedTime(a, v) },
    ];

    const applied: Record<string, unknown> = {};
    const errors: string[] = [];

    for (const { key, requiresGid, apply } of limits) {
      if (!(key in p)) continue;
      if (requiresGid && !gid) continue;
      const v = Number(p[key]);
      if (!Number.isFinite(v)) {
        errors.push(key);
        continue;
      }
      try {
        await apply(v);
        applied[key] = p[key];
      } catch {
        errors.push(key);
      }
    }

    return { ok: errors.length === 0, applied, errors };
  });

  app.post("/api/aria2/change_option", async (req, reply) => {
    if (requireAria2(reply)) return;
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {gid: string, options: {...}}"));
    }
    const gid = String((body as { gid?: unknown }).gid ?? "").trim();
    const rawOptions = (body as { options?: unknown }).options;
    if (!gid || !rawOptions || typeof rawOptions !== "object" || Array.isArray(rawOptions)) {
      return reply
        .code(400)
        .send(errorPayload("invalid_payload", "expected {gid: string, options: {...}}"));
    }
    const options: Record<string, string> = {};
    for (const [k, v] of Object.entries(rawOptions as Record<string, unknown>)) {
      options[k] = String(v);
    }
    try {
      await aria2.changeOption(deps.aria2!, gid, options);
      return { ok: true, gid, applied: options };
    } catch (err) {
      return reply
        .code(502)
        .send(errorPayload("rpc_error", err instanceof Error ? err.message : "aria2 RPC failed"));
    }
  });
}
