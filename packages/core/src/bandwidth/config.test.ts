import { describe, expect, it } from "vitest";
import { bandwidthConfigFrom } from "./config.js";
import { defaultDeclaration } from "../contracts/declaration.js";

describe("bandwidthConfigFrom", () => {
  it("derives use_percent from free_percent and respects defaults", () => {
    const cfg = bandwidthConfigFrom(defaultDeclaration());
    expect(cfg.down_free_percent).toBe(20);
    expect(cfg.down_use_percent).toBeCloseTo(0.8, 5);
    expect(cfg.up_free_percent).toBe(50);
    expect(cfg.up_use_percent).toBeCloseTo(0.5, 5);
    expect(cfg.probe_interval_seconds).toBe(180);
  });

  it("clamps percent to [0,100] and absolute to >= 0", () => {
    const decl = defaultDeclaration();
    const set = (name: string, value: unknown) => {
      decl.uic.preferences.find((p) => p.name === name)!.value = value;
    };
    set("bandwidth_down_free_percent", 250);
    set("bandwidth_down_free_absolute_mbps", -10);
    set("bandwidth_up_free_percent", -1);
    set("bandwidth_up_free_absolute_mbps", "5");
    const cfg = bandwidthConfigFrom(decl);
    expect(cfg.down_free_percent).toBe(100);
    expect(cfg.down_free_absolute_mbps).toBe(0);
    expect(cfg.up_free_percent).toBe(0);
    expect(cfg.up_free_absolute_mbps).toBe(5);
  });

  it("enforces a 30s floor on the probe interval", () => {
    const decl = defaultDeclaration();
    decl.uic.preferences.find((p) => p.name === "bandwidth_probe_interval_seconds")!.value = 5;
    expect(bandwidthConfigFrom(decl).probe_interval_seconds).toBe(30);
  });
});
