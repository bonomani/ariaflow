import type { OpenApiDoc } from "./openapi.js";

export interface DriftReport {
  /** Paths present in `live` but not in `expected`. */
  added: string[];
  /** Paths present in `expected` but missing from `live`. */
  removed: string[];
  /** Paths present in both, but with differing methods. */
  changed: Array<{ path: string; live: string[]; expected: string[] }>;
  /** True when added/removed/changed are all empty. */
  ok: boolean;
}

/**
 * Compare a live OpenAPI doc (from generateOpenApi) against an expected
 * one (parsed from openapi.yaml). Emits a structured drift report so CI
 * can fail loud on additions, removals, or method-set divergences.
 *
 * Method comparison is order-insensitive and case-folded. Tags, summaries,
 * and response shapes are intentionally ignored — those are tracked
 * elsewhere (route validators, in-code docs).
 */
export function diffOpenApi(live: OpenApiDoc, expected: OpenApiDoc): DriftReport {
  const livePaths = new Set(Object.keys(live.paths ?? {}));
  const expPaths = new Set(Object.keys(expected.paths ?? {}));

  const added = [...livePaths].filter((p) => !expPaths.has(p)).sort();
  const removed = [...expPaths].filter((p) => !livePaths.has(p)).sort();

  const changed: DriftReport["changed"] = [];
  for (const path of [...livePaths].sort()) {
    if (!expPaths.has(path)) continue;
    const liveMethods = Object.keys(live.paths![path] ?? {})
      .map((m) => m.toUpperCase())
      .sort();
    const expMethods = Object.keys(expected.paths![path] ?? {})
      .map((m) => m.toUpperCase())
      .sort();
    if (liveMethods.join(",") !== expMethods.join(",")) {
      changed.push({ path, live: liveMethods, expected: expMethods });
    }
  }

  return { added, removed, changed, ok: added.length + removed.length + changed.length === 0 };
}
