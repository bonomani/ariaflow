import { describe, expect, it } from "vitest";
import { defaultDeclaration, prefValue } from "./declaration.js";
import { evaluatePreflight, uccResultToDict } from "./preflight.js";

describe("defaultDeclaration", () => {
  it("declares UCC v2.0 with the two hard gates", () => {
    const d = defaultDeclaration();
    expect(d.meta).toEqual({ contract: "UCC", version: "2.0" });
    const gateNames = d.uic.gates.map((g) => g.name);
    expect(gateNames).toEqual(["aria2_available", "queue_readable"]);
    expect(d.uic.gates.every((g) => g.blocking === "hard")).toBe(true);
  });

  it("returns independent clones", () => {
    const a = defaultDeclaration();
    const b = defaultDeclaration();
    a.uic.preferences[0]!.value = "mutated";
    expect(b.uic.preferences[0]!.value).not.toBe("mutated");
  });

  it("has a sensible default for max_simultaneous_downloads", () => {
    expect(prefValue(defaultDeclaration(), "max_simultaneous_downloads")).toBe(1);
  });
});

describe("prefValue", () => {
  it("returns the pref's current value", () => {
    expect(prefValue(defaultDeclaration(), "bandwidth_down_free_percent")).toBe(20);
  });
  it("returns fallback when missing", () => {
    expect(prefValue(defaultDeclaration(), "no_such_pref", 42)).toBe(42);
  });
});

describe("evaluatePreflight", () => {
  it("passes when all hard gates are satisfied", () => {
    const r = evaluatePreflight(defaultDeclaration(), {
      aria2_available: true,
      queue_readable: true,
    });
    expect(r.status).toBe("pass");
    expect(r.exit_code).toBe(0);
    expect(r.hard_failures).toEqual([]);
    expect(r.gates.every((g) => g.satisfied)).toBe(true);
  });

  it("fails when aria2 is unreachable", () => {
    const r = evaluatePreflight(defaultDeclaration(), {
      aria2_available: false,
      queue_readable: true,
    });
    expect(r.status).toBe("fail");
    expect(r.exit_code).toBe(1);
    expect(r.hard_failures).toEqual(["aria2_available"]);
  });

  it("emits a warning + failure for a paused soft gate", () => {
    const decl = defaultDeclaration();
    decl.uic.gates.push({ name: "paused", class: "readiness", blocking: "soft" });
    const r = evaluatePreflight(decl, {
      aria2_available: true,
      queue_readable: true,
      paused: true,
    });
    // soft gate => warning, no hard failure
    expect(r.hard_failures).toEqual([]);
    expect(r.warnings).toEqual([{ name: "paused", message: "queue is paused" }]);
    expect(r.status).toBe("pass");
  });
});

describe("uccResultToDict", () => {
  it("drops null/undefined/empty-string fields", () => {
    expect(
      uccResultToDict({
        observation: "ok",
        outcome: "ok",
        completion: null,
        message: "",
        reason: "aggregate",
        diff: null,
      }),
    ).toEqual({ observation: "ok", outcome: "ok", reason: "aggregate" });
  });
});
