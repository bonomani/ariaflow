import type { FastifyReply, FastifyRequest } from "fastify";
import {
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
    return {
      ok: true,
      managed: [...MANAGED_ARIA2_OPTIONS].sort(),
      safe: [...SAFE_ARIA2_OPTIONS].sort(),
      unsafe_enabled: Boolean(unsafe?.value),
    };
  });

  // BG-22: the dashboard reads `aria2Options[opt]` straight from the
  // response body (`this.aria2Options = data`), so the options dict
  // must be spread at the top level. aria2 option names are kebab-case
  // ("connect-timeout", "max-tries", ...) so they never collide with
  // our envelope keys (`ok`, `gid`). Same fix for all four endpoints
  // (canonical `get_*` per openapi.yaml + the `global_option` /
  // `option` short-form aliases).
  const globalOptionsHandler = async (
    _req: FastifyRequest,
    reply: FastifyReply,
  ) => {
    if (requireAria2(reply)) return;
    try {
      const opts = await aria2.getGlobalOption(deps.aria2!);
      return withMeta("GET", "/api/aria2/get_global_option", { ok: true, ...opts });
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

  app.get("/api/aria2/get_global_option", globalOptionsHandler);
  app.get("/api/aria2/global_option", globalOptionsHandler);
  app.get<{ Querystring: { gid?: string } }>("/api/aria2/get_option", itemOptionsHandler);
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
        action: "change_options",
        target: "aria2",
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
    const applied: Record<string, unknown> = {};
    const errors: string[] = [];

    const num = (v: unknown): number => {
      const n = Number(v);
      return Number.isFinite(n) ? n : NaN;
    };

    const tryRun = async (key: string, fn: () => Promise<unknown>) => {
      try {
        await fn();
        applied[key] = p[key];
      } catch {
        errors.push(key);
      }
    };

    if ("max_overall_download_limit" in p) {
      const v = num(p.max_overall_download_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_overall_download_limit", () =>
          aria2.setMaxOverallDownloadLimit(deps.aria2!, v),
        );
      } else errors.push("max_overall_download_limit");
    }
    if ("max_overall_upload_limit" in p) {
      const v = num(p.max_overall_upload_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_overall_upload_limit", () =>
          aria2.setMaxOverallUploadLimit(deps.aria2!, v),
        );
      } else errors.push("max_overall_upload_limit");
    }
    if ("max_download_limit" in p && gid) {
      const v = num(p.max_download_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_download_limit", () => aria2.setMaxDownloadLimit(deps.aria2!, gid, v));
      } else errors.push("max_download_limit");
    }
    if ("max_upload_limit" in p && gid) {
      const v = num(p.max_upload_limit);
      if (Number.isFinite(v)) {
        await tryRun("max_upload_limit", () => aria2.setMaxUploadLimit(deps.aria2!, gid, v));
      } else errors.push("max_upload_limit");
    }
    if ("seed_ratio" in p) {
      const v = num(p.seed_ratio);
      if (Number.isFinite(v)) {
        await tryRun("seed_ratio", () => aria2.setSeedRatio(deps.aria2!, v));
      } else errors.push("seed_ratio");
    }
    if ("seed_time" in p) {
      const v = num(p.seed_time);
      if (Number.isFinite(v)) {
        await tryRun("seed_time", () => aria2.setSeedTime(deps.aria2!, v));
      } else errors.push("seed_time");
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
