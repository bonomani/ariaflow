import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { diffOpenApi, formatDriftReport, loadOpenApiYaml } from "./drift.js";
import type { OpenApiDoc } from "./openapi.js";

const doc = (paths: Record<string, Record<string, unknown>>): OpenApiDoc => ({
  openapi: "3.0.3",
  info: { title: "t", version: "0" },
  tags: [],
  paths: paths as OpenApiDoc["paths"],
});

describe("diffOpenApi", () => {
  it("reports ok when both docs match exactly", () => {
    const a = doc({ "/x": { get: {} } });
    const b = doc({ "/x": { get: {} } });
    expect(diffOpenApi(a, b)).toEqual({ added: [], removed: [], changed: [], ok: true });
  });

  it("flags paths added on the live side", () => {
    const live = doc({ "/x": { get: {} }, "/y": { post: {} } });
    const exp = doc({ "/x": { get: {} } });
    const r = diffOpenApi(live, exp);
    expect(r.added).toEqual(["/y"]);
    expect(r.removed).toEqual([]);
    expect(r.ok).toBe(false);
  });

  it("flags paths missing from the live side", () => {
    const live = doc({ "/x": { get: {} } });
    const exp = doc({ "/x": { get: {} }, "/y": { post: {} } });
    const r = diffOpenApi(live, exp);
    expect(r.removed).toEqual(["/y"]);
  });

  it("flags method-set drift on shared paths (case-insensitive)", () => {
    const live = doc({ "/x": { get: {}, post: {} } });
    const exp = doc({ "/x": { GET: {} } });
    const r = diffOpenApi(live, exp);
    expect(r.changed).toEqual([{ path: "/x", live: ["GET", "POST"], expected: ["GET"] }]);
    expect(r.ok).toBe(false);
  });

  it("returns sorted, stable lists", () => {
    const live = doc({ "/b": { get: {} }, "/a": { get: {} }, "/c": { get: {} } });
    const exp = doc({});
    expect(diffOpenApi(live, exp).added).toEqual(["/a", "/b", "/c"]);
  });

  it("ignores Fastify's `*` catch-all (cannot be represented in OpenAPI)", () => {
    const live = doc({ "/x": { get: {} }, "*": { get: {} } });
    const exp = doc({ "/x": { get: {} } });
    expect(diffOpenApi(live, exp)).toEqual({
      added: [],
      removed: [],
      changed: [],
      ok: true,
    });
  });
});

describe("loadOpenApiYaml", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "ariaflow-yaml-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("parses an OpenAPI yaml document", async () => {
    const path = join(dir, "openapi.yaml");
    writeFileSync(
      path,
      [
        "openapi: 3.0.3",
        "info:",
        "  title: x",
        "  version: '0'",
        "paths:",
        "  /api/health:",
        "    get:",
        "      summary: health",
        "",
      ].join("\n"),
    );
    const doc = await loadOpenApiYaml(path);
    expect(doc.openapi).toBe("3.0.3");
    expect(doc.paths["/api/health"]).toBeTruthy();
  });

  it("rejects non-OpenAPI yaml shapes", async () => {
    const path = join(dir, "bad.yaml");
    writeFileSync(path, "foo: bar\n");
    await expect(loadOpenApiYaml(path)).rejects.toThrow(/paths/);
  });
});

describe("formatDriftReport", () => {
  const doc = (paths: Record<string, Record<string, unknown>>): OpenApiDoc => ({
    openapi: "3.0.3",
    info: { title: "t", version: "0" },
    tags: [],
    paths: paths as OpenApiDoc["paths"],
  });

  it("returns an empty string when ok=true", () => {
    expect(formatDriftReport(diffOpenApi(doc({}), doc({})))).toBe("");
  });

  it("renders added/removed/changed sections", () => {
    const live = doc({ "/a": { get: {}, post: {} }, "/b": { get: {} } });
    const exp = doc({ "/a": { get: {} }, "/c": { get: {} } });
    const text = formatDriftReport(diffOpenApi(live, exp));
    expect(text).toContain("+ /b");
    expect(text).toContain("- /c");
    expect(text).toContain("! /a");
    expect(text).toContain("live=GET,POST");
    expect(text).toContain("expected=GET");
  });
});
