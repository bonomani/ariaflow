import { prefValue, type Declaration } from "../contracts/declaration.js";

export interface BandwidthConfig {
  down_free_percent: number;
  down_free_absolute_mbps: number;
  down_use_percent: number;
  up_free_percent: number;
  up_free_absolute_mbps: number;
  up_use_percent: number;
  probe_interval_seconds: number;
}

const clampPct = (v: unknown): number =>
  Math.max(0, Math.min(100, Math.trunc(Number(v) || 0)));
const clampAbs = (v: unknown): number => Math.max(0, Number(v) || 0);

/**
 * Resolve the bandwidth config from a declaration: pct clamped to
 * [0,100], abs >= 0, probe_interval_seconds with a floor of 30. The
 * use_percent fields are derived from free_percent so callers don't
 * recompute them.
 */
export function bandwidthConfigFrom(declaration: Declaration): BandwidthConfig {
  const downFreePct = clampPct(prefValue(declaration, "bandwidth_down_free_percent", 20));
  const downFreeAbs = clampAbs(prefValue(declaration, "bandwidth_down_free_absolute_mbps", 0));
  const upFreePct = clampPct(prefValue(declaration, "bandwidth_up_free_percent", 50));
  const upFreeAbs = clampAbs(prefValue(declaration, "bandwidth_up_free_absolute_mbps", 0));
  const intervalRaw = Number(prefValue(declaration, "bandwidth_probe_interval_seconds", 180));
  const interval = Math.max(30, Math.trunc(Number.isFinite(intervalRaw) ? intervalRaw : 180));
  return {
    down_free_percent: downFreePct,
    down_free_absolute_mbps: downFreeAbs,
    down_use_percent: 1 - downFreePct / 100,
    up_free_percent: upFreePct,
    up_free_absolute_mbps: upFreeAbs,
    up_use_percent: 1 - upFreePct / 100,
    probe_interval_seconds: interval,
  };
}
