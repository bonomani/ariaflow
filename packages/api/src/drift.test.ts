import { describe, expect, it } from "vitest";
import { diffOpenApi } from "./drift.js";
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
});
