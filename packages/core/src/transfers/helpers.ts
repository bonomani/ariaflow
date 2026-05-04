import { prefValue, type Declaration } from "../contracts/declaration.js";

/**
 * Generate a readable failure message for an RPC error during a named
 * action (pause/resume/etc). Prefers the error's own text, otherwise
 * classifies by name suffix.
 */
export function rpcFailureMessage(action: string, err: unknown): string {
  if (err instanceof Error) {
    const text = err.message?.trim();
    if (text) return text;
    const name = (err.name ?? err.constructor?.name ?? "").toLowerCase();
    if (name.includes("timeout") || name.includes("abort"))
      return `aria2 ${action} RPC timed out`;
    if (name.includes("connection") || name.includes("network"))
      return `aria2 ${action} RPC connection failed`;
  }
  return `aria2 ${action} RPC failed`;
}

export type DedupActiveTransferAction = "pause" | "remove" | "ignore";

/**
 * Resolve the `duplicate_active_transfer_action` preference. Defaults
 * to `remove` if the pref is missing or the value is unrecognised.
 */
export function dedupActiveTransferAction(
  declaration: Declaration,
): DedupActiveTransferAction {
  const raw = String(prefValue(declaration, "duplicate_active_transfer_action", "remove"))
    .trim()
    .toLowerCase();
  if (raw === "pause" || raw === "remove" || raw === "ignore") return raw;
  return "remove";
}

/**
 * Resolve the `max_simultaneous_downloads` preference. Returns 0 (no
 * cap) for missing/unparseable values; never returns a negative number.
 */
export function maxSimultaneousDownloads(declaration: Declaration): number {
  const raw = prefValue(declaration, "max_simultaneous_downloads", 0);
  const n = Number(raw);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.trunc(n));
}
