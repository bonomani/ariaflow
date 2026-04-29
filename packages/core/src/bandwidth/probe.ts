import {
  BITS_PER_MEGABIT,
  BYTES_PER_MEGABIT,
  capBytesPerSecFromMbps,
  capMbpsFromBytesPerSec,
} from "./units.js";

export interface BandwidthProbe {
  source: "networkquality" | "default";
  reason: string;
  downlink_mbps: number | null;
  cap_mbps: number;
  cap_bytes_per_sec: number;
  uplink_mbps?: number;
  responsiveness_rpm?: number;
  interface_name?: string;
  command?: string;
  command_mode?: string;
  partial?: boolean;
}

const round1 = (n: number): number => Math.round(n * 10) / 10;

function coerceFloat(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export function defaultBandwidthProbe(opts: {
  floorMbps: number;
  reason: string;
  partial?: boolean;
  command?: string;
}): BandwidthProbe {
  const probe: BandwidthProbe = {
    source: "default",
    reason: opts.reason,
    downlink_mbps: null,
    cap_mbps: round1(opts.floorMbps),
    cap_bytes_per_sec: Math.trunc(opts.floorMbps * BYTES_PER_MEGABIT),
  };
  if (opts.partial) probe.partial = true;
  if (opts.command) probe.command = opts.command;
  return probe;
}

const DOWNLINK_RE = /Downlink(?:\s+capacity)?:\s+([\d.]+)\s+Mbps/i;

/**
 * Parse macOS `networkQuality` output (JSON or human-text fallback).
 * Returns null when the input has no usable downlink reading.
 */
export function parseNetworkQualityOutput(
  output: string,
  opts: { percent: number; floorMbps: number },
): BandwidthProbe | null {
  const text = (output ?? "").trim();
  if (!text) return null;

  let payload: unknown = null;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = null;
  }

  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const obj = payload as Record<string, unknown>;
    const dlBps = coerceFloat(obj.dl_throughput);
    if (dlBps && dlBps > 0) {
      const downlinkMbps = round1(dlBps / BITS_PER_MEGABIT);
      const capBytesPerSec = capBytesPerSecFromMbps(downlinkMbps, opts.percent, opts.floorMbps);
      const probe: BandwidthProbe = {
        source: "networkquality",
        reason: "probe_complete",
        downlink_mbps: downlinkMbps,
        cap_mbps: capMbpsFromBytesPerSec(capBytesPerSec),
        cap_bytes_per_sec: capBytesPerSec,
      };
      const ulBps = coerceFloat(obj.ul_throughput);
      if (ulBps && ulBps > 0) probe.uplink_mbps = round1(ulBps / BITS_PER_MEGABIT);
      const responsiveness = coerceFloat(obj.dl_responsiveness) ?? coerceFloat(obj.responsiveness);
      if (responsiveness !== null) probe.responsiveness_rpm = round1(responsiveness);
      const iface = obj.interface_name;
      if (typeof iface === "string" && iface) probe.interface_name = iface;
      return probe;
    }
  }

  const m = DOWNLINK_RE.exec(text);
  if (m) {
    const downlinkMbps = Number(m[1]);
    const capBytesPerSec = capBytesPerSecFromMbps(downlinkMbps, opts.percent, opts.floorMbps);
    return {
      source: "networkquality",
      reason: "probe_complete",
      downlink_mbps: round1(downlinkMbps),
      cap_mbps: capMbpsFromBytesPerSec(capBytesPerSec),
      cap_bytes_per_sec: capBytesPerSec,
      command_mode: "text_fallback",
    };
  }
  return null;
}

export const NETWORKQUALITY_PROBE_INTERVAL_SEC = 180;

/**
 * Decide whether enough time has passed since the last probe to run another.
 */
export function shouldProbeBandwidth(
  state: { last_bandwidth_probe_at?: unknown },
  now: number = Date.now() / 1000,
  intervalSec: number = NETWORKQUALITY_PROBE_INTERVAL_SEC,
): boolean {
  const last = coerceFloat(state.last_bandwidth_probe_at);
  if (last === null) return true;
  return now - last >= intervalSec;
}
