import { describe, expect, it } from "vitest";
import { uccEnvelope } from "./ucc.js";

describe("uccEnvelope", () => {
  it("emits the canonical UCC v2.0 meta + result shape", () => {
    expect(uccEnvelope({ target: "queue", observed: true, outcome: "ok" })).toEqual({
      meta: { contract: "UCC", version: "2.0", target: "queue" },
      result: {
        observation: "ok",
        outcome: "ok",
        reason: "aggregate",
        target: "queue",
      },
    });
  });

  it("maps observed=false to observation='failed'", () => {
    const env = uccEnvelope({ target: "x", observed: false, outcome: "failed" });
    expect(env.result.observation).toBe("failed");
  });

  it("includes optional fields when provided, omits them otherwise", () => {
    const env = uccEnvelope({
      target: "queue",
      observed: true,
      outcome: "ok",
      completion: "full",
      detail: "all rows reconciled",
      commands: ["a", "b"],
      reason: "manual",
    });
    expect(env.result).toEqual({
      observation: "ok",
      outcome: "ok",
      reason: "manual",
      target: "queue",
      completion: "full",
      message: "all rows reconciled",
      commands: ["a", "b"],
    });
  });

  it("does NOT include null/undefined optional fields", () => {
    const env = uccEnvelope({
      target: "x",
      observed: true,
      outcome: "ok",
      completion: null,
      detail: null,
      commands: null,
    });
    expect(env.result).toEqual({
      observation: "ok",
      outcome: "ok",
      reason: "aggregate",
      target: "x",
    });
  });
});
