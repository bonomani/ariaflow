import { prefValue, type Declaration } from "../contracts/declaration.js";

/**
 * aria2 options handled by dedicated set_* helpers (Phase 6 dispatch).
 * These are rejected from the generic change_options endpoint to keep
 * the bandwidth/seed pipeline as the only writer.
 */
export const MANAGED_ARIA2_OPTIONS: ReadonlySet<string> = new Set([
  "max-overall-download-limit",
  "max-overall-upload-limit",
  "max-download-limit",
  "max-upload-limit",
  "seed-ratio",
  "seed-time",
]);

/**
 * Options the generic API allows without the `aria2_unsafe_options`
 * preference set to true.
 */
export const SAFE_ARIA2_OPTIONS: ReadonlySet<string> = new Set([
  "max-concurrent-downloads",
  "max-connection-per-server",
  "split",
  "min-split-size",
  "timeout",
  "connect-timeout",
]);

export type ChangeOptionsValidation =
  | { ok: true; options: Record<string, string> }
  | { ok: false; error: "managed_options" | "rejected_options" | "empty_options"; message: string };

/**
 * Pure validator for the body of POST /api/aria2/change_global_option.
 * Mirrors aria2_rpc.aria2_change_options' pre-RPC checks: forbids
 * managed-set options, rejects everything outside SAFE_ARIA2_OPTIONS
 * unless `aria2_unsafe_options` preference is true, and demands a
 * non-empty body.
 */
export function validateChangeOptions(
  payload: unknown,
  declaration: Declaration,
): ChangeOptionsValidation {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, error: "empty_options", message: "no options provided" };
  }
  const entries = Object.entries(payload as Record<string, unknown>);
  if (entries.length === 0) {
    return { ok: false, error: "empty_options", message: "no options provided" };
  }
  const options: Record<string, string> = {};
  for (const [k, v] of entries) {
    options[k] = String(v);
  }
  const managed = Object.keys(options).filter((k) => MANAGED_ARIA2_OPTIONS.has(k));
  if (managed.length > 0) {
    return {
      ok: false,
      error: "managed_options",
      message: `use dedicated aria2_set_* functions for: ${managed.join(", ")}`,
    };
  }
  const unsafeMode = Boolean(prefValue(declaration, "aria2_unsafe_options", false));
  if (!unsafeMode) {
    const rejected = Object.keys(options).filter((k) => !SAFE_ARIA2_OPTIONS.has(k));
    if (rejected.length > 0) {
      return {
        ok: false,
        error: "rejected_options",
        message: `unsafe options (enable aria2_unsafe_options preference): ${rejected.join(", ")}`,
      };
    }
  }
  return { ok: true, options };
}
