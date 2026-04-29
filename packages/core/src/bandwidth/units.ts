export const BITS_PER_MEGABIT = 1_000_000;
export const BYTES_PER_MEGABIT = 125_000;

const round1 = (n: number): number => Math.round(n * 10) / 10;

export function aria2SpeedValue(capBytesPerSec: number): string {
  return String(Math.max(0, Math.trunc(capBytesPerSec)));
}

/**
 * Compute byte/sec cap from a measured downlink (Mbps), a fractional usage
 * `percent` (0..1), and a minimum floor in Mbps.
 */
export function capBytesPerSecFromMbps(
  downlinkMbps: number,
  percent: number,
  floorMbps: number,
): number {
  const floorBytes = Math.trunc(floorMbps * BYTES_PER_MEGABIT);
  const computed = Math.trunc(downlinkMbps * percent * BYTES_PER_MEGABIT);
  return Math.max(floorBytes, computed);
}

export function capMbpsFromBytesPerSec(capBytesPerSec: number): number {
  return round1((capBytesPerSec * 8) / BITS_PER_MEGABIT);
}

/**
 * Apply "free bandwidth" reservation: keep `freePercent` of the measured rate
 * unused, plus an absolute MBps reservation if set. Returns the cap in Mbps,
 * or null when there's nothing to cap.
 */
export function applyFreeBandwidthCap(
  measuredMbps: number | null | undefined,
  freePercent: number,
  freeAbsMbps: number,
): number | null {
  if (!measuredMbps || measuredMbps <= 0) return null;
  const fromPct = measuredMbps * (1 - freePercent / 100);
  let cap = fromPct;
  if (freeAbsMbps > 0) cap = Math.min(cap, measuredMbps - freeAbsMbps);
  return Math.max(0, round1(cap));
}
