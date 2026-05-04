import { existsSync } from "node:fs";
import { which } from "../bonjour/bonjour.js";

const CANDIDATES = [
  "/usr/bin/networkQuality",
  "/usr/bin/networkquality",
  "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkQuality",
  "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkquality",
];

/**
 * Locate the macOS `networkQuality` binary. Probes PATH first under both
 * casings, then walks a list of well-known absolute paths used on
 * recent macOS releases. Mirrors bandwidth._find_networkquality.
 *
 * `candidates` defaults to the OS fallback list; tests pass `[]` to
 * isolate from the real filesystem.
 */
export function findNetworkQuality(
  env: NodeJS.ProcessEnv = process.env,
  candidates: readonly string[] = CANDIDATES,
): string | null {
  for (const name of ["networkQuality", "networkquality"]) {
    const found = which(name, env);
    if (found) return found;
  }
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

export interface NetworkQualityStatus {
  installed: boolean;
  usable: boolean;
  version: string | null;
  reason: "ready" | "missing";
  message: string;
  command?: string;
}

/**
 * Status payload mirroring install.networkquality_status: surfaces
 * whether the macOS connectivity probe is available and where it lives.
 */
export function networkqualityStatus(
  env: NodeJS.ProcessEnv = process.env,
  candidates: readonly string[] = CANDIDATES,
): NetworkQualityStatus {
  const cmd = findNetworkQuality(env, candidates);
  if (!cmd) {
    return {
      installed: false,
      usable: false,
      version: null,
      reason: "missing",
      message: "networkquality tool not found",
    };
  }
  return {
    installed: true,
    usable: true,
    version: null,
    reason: "ready",
    message: `networkquality available at ${cmd}; ariaflow-server uses bounded -u -c -s probes at startup and every 180s during runs`,
    command: cmd,
  };
}
