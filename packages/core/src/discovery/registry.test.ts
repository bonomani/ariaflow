import { describe, expect, it } from "vitest";
import { PeerRegistry } from "./registry.js";

const peer = (instance: string) => ({
  instance,
  status: "browsed" as const,
  last_seen: 0,
});

describe("PeerRegistry", () => {
  it("starts empty and grows on upsert", () => {
    const r = new PeerRegistry();
    expect(r.size).toBe(0);
    r.upsert(peer("a"));
    expect(r.size).toBe(1);
    expect(r.get("a")?.instance).toBe("a");
  });

  it("upsert is keyed by instance — second call replaces the first", () => {
    const r = new PeerRegistry();
    r.upsert(peer("a"));
    r.upsert(peer("a"));
    expect(r.size).toBe(1);
  });

  it("remove returns the prior value and shrinks the size", () => {
    const r = new PeerRegistry();
    r.upsert(peer("a"));
    r.upsert(peer("b"));
    expect(r.remove("a")?.instance).toBe("a");
    expect(r.size).toBe(1);
    expect(r.remove("missing")).toBeUndefined();
  });

  it("list returns a snapshot in insertion order", () => {
    const r = new PeerRegistry();
    r.upsert(peer("a"));
    r.upsert(peer("b"));
    expect(r.list().map((p) => p.instance)).toEqual(["a", "b"]);
  });

  it("clear empties the registry", () => {
    const r = new PeerRegistry();
    r.upsert(peer("a"));
    r.clear();
    expect(r.size).toBe(0);
  });
});
