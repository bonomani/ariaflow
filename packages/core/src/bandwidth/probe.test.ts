import { describe, expect, it } from "vitest";
import {
  defaultBandwidthProbe,
  parseNetworkQualityOutput,
  shouldProbeBandwidth,
} from "./probe.js";

describe("defaultBandwidthProbe", () => {
  it("builds a default-source probe at the floor", () => {
    const p = defaultBandwidthProbe({ floorMbps: 5, reason: "probe_unavailable" });
    expect(p).toMatchObject({
      source: "default",
      reason: "probe_unavailable",
      downlink_mbps: null,
      cap_mbps: 5,
      cap_bytes_per_sec: 5 * 125_000,
    });
    expect(p.partial).toBeUndefined();
    expect(p.command).toBeUndefined();
  });
  it("includes partial / command when provided", () => {
    const p = defaultBandwidthProbe({
      floorMbps: 2,
      reason: "probe_timeout_no_parse",
      partial: true,
      command: "networkQuality -u",
    });
    expect(p.partial).toBe(true);
    expect(p.command).toBe("networkQuality -u");
  });
});

describe("parseNetworkQualityOutput", () => {
  it("returns null on empty", () => {
    expect(parseNetworkQualityOutput("", { percent: 0.8, floorMbps: 2 })).toBeNull();
  });

  it("parses JSON output with throughput", () => {
    const json = JSON.stringify({
      dl_throughput: 100_000_000, // 100 Mbps
      ul_throughput: 25_000_000,
      dl_responsiveness: 740.4,
      interface_name: "en0",
    });
    const p = parseNetworkQualityOutput(json, { percent: 0.8, floorMbps: 2 });
    expect(p).not.toBeNull();
    expect(p!.source).toBe("networkquality");
    expect(p!.downlink_mbps).toBe(100);
    expect(p!.uplink_mbps).toBe(25);
    expect(p!.responsiveness_rpm).toBe(740.4);
    expect(p!.interface_name).toBe("en0");
    expect(p!.cap_bytes_per_sec).toBe(80 * 125_000);
  });

  it("falls back to text parsing for human output", () => {
    const text = "Uplink capacity: 30.0 Mbps\nDownlink capacity: 250.5 Mbps\n";
    const p = parseNetworkQualityOutput(text, { percent: 0.8, floorMbps: 2 });
    expect(p).not.toBeNull();
    expect(p!.downlink_mbps).toBe(250.5);
    expect(p!.command_mode).toBe("text_fallback");
  });

  it("returns null when no downlink can be parsed", () => {
    expect(parseNetworkQualityOutput("garbage", { percent: 0.8, floorMbps: 2 })).toBeNull();
  });
});

describe("shouldProbeBandwidth", () => {
  it("returns true when there's no prior probe", () => {
    expect(shouldProbeBandwidth({}, 1000, 180)).toBe(true);
    expect(shouldProbeBandwidth({ last_bandwidth_probe_at: "nope" }, 1000, 180)).toBe(true);
  });
  it("respects the interval", () => {
    expect(shouldProbeBandwidth({ last_bandwidth_probe_at: 900 }, 1000, 180)).toBe(false);
    expect(shouldProbeBandwidth({ last_bandwidth_probe_at: 700 }, 1000, 180)).toBe(true);
  });
});
