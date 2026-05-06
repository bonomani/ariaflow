import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { detectAriaflowManagedBy, detectLaunchdLabel } from "./ariaflow_self.js";

/**
 * BG-62: build the launchd bootout+bootstrap suffix that follows a
 * `brew upgrade ariaflow-server` so the running process picks up the
 * new bottle without a manual restart.
 *
 * Returns the shell suffix (without leading separator) or null when
 * not applicable: process not under launchd, no detectable label, or
 * plist not in `~/Library/LaunchAgents` (operator-managed elsewhere —
 * we don't second-guess their layout).
 */
export function buildPostUpgradeRestartSuffix(): string | null {
  if (detectAriaflowManagedBy() !== "launchd") return null;
  const label = detectLaunchdLabel();
  if (!label) return null;
  const plist = join(homedir(), "Library", "LaunchAgents", `${label}.plist`);
  if (!existsSync(plist)) return null;
  const uid = process.getuid?.() ?? 0;
  const target = `gui/${uid}/${label}`;
  const domain = `gui/${uid}`;
  return `launchctl bootout ${target} 2>/dev/null; launchctl bootstrap ${domain} ${plist}`;
}
