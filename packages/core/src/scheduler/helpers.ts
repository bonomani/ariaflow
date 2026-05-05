import { prefValue, type Declaration } from "../contracts/declaration.js";

export interface DiskCheckResult {
  ok: boolean;
  percentUsed: number;
}

/**
 * Pure disk-space gate: caller resolves the configured download dir +
 * threshold and a usage probe. Returns ok=false when usage >= threshold;
 * ok=true with 0 when the threshold is disabled or the probe fails.
 * Split this way so tests can inject a fake usage probe without
 * touching the filesystem.
 */
export function checkDiskSpace(opts: {
  maxPercent: number;
  probe: () => { used: number; total: number } | null;
}): DiskCheckResult {
  if (opts.maxPercent === 0) return { ok: true, percentUsed: 0 };
  const usage = opts.probe();
  if (!usage || usage.total <= 0) return { ok: true, percentUsed: 0 };
  const percentUsed = Math.round((usage.used / usage.total) * 1000) / 10;
  return { ok: percentUsed < opts.maxPercent, percentUsed };
}

export function maxDiskPercent(declaration: Declaration): number {
  const raw = prefValue(declaration, "max_disk_usage_percent", 90);
  return raw === null || raw === undefined ? 90 : Number(raw);
}
