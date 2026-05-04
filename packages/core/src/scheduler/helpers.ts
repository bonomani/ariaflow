import type { QueueItemRecord } from "../queue/types.js";
import { prefValue, type Declaration } from "../contracts/declaration.js";

/**
 * Best-effort human message from a thrown RPC poll error: prefer the
 * exception's own text; otherwise classify by error name
 * (Timeout / Connection / *).
 */
export function rpcPollFailureMessage(err: unknown): string {
  if (err instanceof Error) {
    const text = err.message?.trim();
    if (text) return text;
    const name = (err.name ?? err.constructor?.name ?? "").toLowerCase();
    if (name.includes("timeout") || name.includes("abort"))
      return "aria2 status RPC timed out";
    if (name.includes("connection") || name.includes("network"))
      return "aria2 status RPC connection failed";
  }
  return "aria2 status RPC failed";
}

/**
 * Resolve the desired (running|paused) state of an item:
 * - explicit `desired_state` of "running" or "paused" wins
 * - else `status === "paused"` -> "paused"
 * - else "running"
 */
export function desiredState(item: QueueItemRecord): "running" | "paused" {
  const desired = String(item.desired_state ?? "").trim().toLowerCase();
  if (desired === "running" || desired === "paused") return desired;
  if (String(item.status ?? "").trim().toLowerCase() === "paused") return "paused";
  return "running";
}

/**
 * The status to put an item back into the queue with after a recovery
 * cycle: "paused" when the user wanted it paused, otherwise "queued".
 */
export function reinjectStatus(item: QueueItemRecord): "paused" | "queued" {
  return desiredState(item) === "paused" ? "paused" : "queued";
}

/**
 * Pull the auto_preflight_on_run preference out of the declaration.
 */
export function autoPreflightOnRun(declaration: Declaration): boolean {
  return Boolean(prefValue(declaration, "auto_preflight_on_run", false));
}

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
