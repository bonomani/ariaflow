import { readFile } from "node:fs/promises";
import { parse as parseYaml } from "yaml";
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
  // Fastify registers `*` as a 404 catch-all; OpenAPI cannot represent
  // a wildcard, so it is excluded from drift comparison.
  const livePaths = new Set(Object.keys(live.paths ?? {}).filter((p) => p !== "*"));
  const expPaths = new Set(Object.keys(expected.paths ?? {}));

  const added = [...livePaths].filter((p) => !expPaths.has(p)).sort();
  const removed = [...expPaths].filter((p) => !livePaths.has(p)).sort();

  const changed: DriftReport["changed"] = [];
  for (const path of [...livePaths].sort()) {
    if (!expPaths.has(path)) continue;
    // HEAD is auto-attached to every GET by Fastify; the canonical
    // openapi.yaml never declares it, so dropping it here removes a
    // class of false-positive method drift entries.
    const liveMethods = Object.keys(live.paths![path] ?? {})
      .map((m) => m.toUpperCase())
      .filter((m) => m !== "HEAD")
      .sort();
    const expMethods = Object.keys(expected.paths![path] ?? {})
      .map((m) => m.toUpperCase())
      .filter((m) => m !== "HEAD")
      .sort();
    if (liveMethods.join(",") !== expMethods.join(",")) {
      changed.push({ path, live: liveMethods, expected: expMethods });
    }
  }

  return { added, removed, changed, ok: added.length + removed.length + changed.length === 0 };
}

/**
 * Read an OpenAPI document from a YAML file at `path`. Throws when the
 * file is missing or doesn't parse to an object with a `paths` key.
 */
export async function loadOpenApiYaml(path: string): Promise<OpenApiDoc> {
  const text = await readFile(path, "utf8");
  const parsed = parseYaml(text);
  if (!parsed || typeof parsed !== "object" || !("paths" in parsed)) {
    throw new Error(`expected an OpenAPI document with a 'paths' key at ${path}`);
  }
  return parsed as OpenApiDoc;
}

/**
 * Render a DriftReport as a human-readable string. Empty when ok=true.
 */
export function formatDriftReport(report: DriftReport): string {
  if (report.ok) return "";
  const lines: string[] = [];
  if (report.added.length) {
    lines.push("Paths in live but not in spec:");
    for (const p of report.added) lines.push(`  + ${p}`);
  }
  if (report.removed.length) {
    lines.push("Paths in spec but not in live:");
    for (const p of report.removed) lines.push(`  - ${p}`);
  }
  if (report.changed.length) {
    lines.push("Method-set drift:");
    for (const c of report.changed) {
      lines.push(`  ! ${c.path}  live=${c.live.join(",")}  expected=${c.expected.join(",")}`);
    }
  }
  return lines.join("\n") + "\n";
}
