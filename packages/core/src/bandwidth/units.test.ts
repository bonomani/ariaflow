import { describe, expect, it } from "vitest";
import {
  applyFreeBandwidthCap,
  aria2SpeedValue,
  capBytesPerSecFromMbps,
  capMbpsFromBytesPerSec,
} from "./units.js";

describe("aria2SpeedValue", () => {
  it("clamps to 0 and truncates", () => {
    expect(aria2SpeedValue(0)).toBe("0");
    expect(aria2SpeedValue(-100)).toBe("0");
    expect(aria2SpeedValue(123.7)).toBe("123");
  });
});

describe("capBytesPerSecFromMbps", () => {
  it("respects the floor", () => {
    expect(capBytesPerSecFromMbps(1, 0.5, 2)).toBe(2 * 125_000);
  });
  it("uses percent of measured when above floor", () => {
    expect(capBytesPerSecFromMbps(100, 0.8, 2)).toBe(80 * 125_000);
  });
});

describe("capMbpsFromBytesPerSec round-trip", () => {
  it("inverts capBytesPerSecFromMbps within rounding", () => {
    const bps = capBytesPerSecFromMbps(50, 1, 1);
    expect(capMbpsFromBytesPerSec(bps)).toBe(50);
  });
});

describe("applyFreeBandwidthCap", () => {
  it("returns null for null/zero/negative", () => {
    expect(applyFreeBandwidthCap(null, 20, 0)).toBeNull();
    expect(applyFreeBandwidthCap(0, 20, 0)).toBeNull();
    expect(applyFreeBandwidthCap(-1, 20, 0)).toBeNull();
  });
  it("applies free percent only", () => {
    expect(applyFreeBandwidthCap(100, 20, 0)).toBe(80);
  });
  it("takes the tighter of percent and absolute reservation", () => {
    expect(applyFreeBandwidthCap(100, 20, 50)).toBe(50);
    expect(applyFreeBandwidthCap(100, 60, 10)).toBe(40);
  });
  it("never goes below 0", () => {
    expect(applyFreeBandwidthCap(10, 0, 100)).toBe(0);
  });
});
