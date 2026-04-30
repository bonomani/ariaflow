import { describe, expect, it } from "vitest";
import {
  _resetFreshness,
  getFreshness,
  listFreshness,
  registerDefaultFreshness,
  registerFreshness,
  withMeta,
} from "./freshness.js";

describe("freshness registry", () => {
  it("registerDefaultFreshness covers the BG-31 #4 endpoints", () => {
    _resetFreshness();
    registerDefaultFreshness();
    expect(getFreshness("GET", "/api/status")).toEqual({
      freshness: "live",
      transport: "sse",
      transport_topics: ["items", "scheduler"],
    });
    expect(getFreshness("GET", "/api/lifecycle")).toMatchObject({ freshness: "warm", ttl_s: 30 });
    expect(getFreshness("GET", "/api/bandwidth")).toMatchObject({
      freshness: "on-action",
      revalidate_on: ["POST /api/bandwidth/probe"],
    });
    expect(getFreshness("GET", "/api/health")).toEqual({ freshness: "bootstrap" });
    expect(getFreshness("GET", "/api/version")).toEqual({ freshness: "bootstrap" });
    expect(getFreshness("GET", "/api/log")).toMatchObject({ freshness: "swr", ttl_s: 10 });
    expect(getFreshness("GET", "/api/_meta")).toEqual({ freshness: "bootstrap" });
  });

  it("validateMeta rejects warm/swr without ttl_s", () => {
    _resetFreshness();
    expect(() => registerFreshness("GET", "/x", { freshness: "warm" })).toThrow(/ttl_s/);
    expect(() => registerFreshness("GET", "/x", { freshness: "swr" })).toThrow(/ttl_s/);
  });

  it("validateMeta rejects on-action without revalidate_on", () => {
    _resetFreshness();
    expect(() => registerFreshness("GET", "/x", { freshness: "on-action" })).toThrow(
      /revalidate_on/,
    );
  });

  it("validateMeta rejects live without transport", () => {
    _resetFreshness();
    expect(() =>
      registerFreshness("GET", "/x", { freshness: "live" } as never),
    ).toThrow(/transport/);
  });

  it("withMeta stamps meta on the body", () => {
    _resetFreshness();
    registerFreshness("GET", "/api/health", { freshness: "bootstrap" });
    expect(withMeta("GET", "/api/health", { ok: true })).toEqual({
      ok: true,
      meta: { freshness: "bootstrap" },
    });
  });

  it("withMeta throws for unregistered keys (no implicit endpoints)", () => {
    _resetFreshness();
    expect(() => withMeta("GET", "/api/nope", { ok: true })).toThrow(/no registry entry/);
  });

  it("listFreshness returns a sorted array", () => {
    _resetFreshness();
    registerDefaultFreshness();
    const list = listFreshness();
    const paths = list.map((e) => e.path);
    expect([...paths]).toEqual([...paths].sort());
    expect(paths).toContain("/api/_meta");
  });
});
