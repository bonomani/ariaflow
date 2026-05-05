import { prefValue, type Declaration } from "../contracts/declaration.js";

type DedupActiveTransferAction = "pause" | "remove" | "ignore";

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
