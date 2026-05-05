import type { Aria2Client } from "../aria2/client.js";
import type { Declaration } from "../contracts/declaration.js";
import { prefValue } from "../contracts/declaration.js";
import { checkDiskSpace, maxDiskPercent } from "./helpers.js";

/**
 * Try `aria2.getVersion` and report reachability. Returns:
 *   - null when no client is wired (the caller decides how to interpret),
 *   - true when the call succeeded,
 *   - false on any RPC error.
 *
 * Centralized so the four routes that ask "is aria2 up right now?"
 * (preflight, /api/active, /api/scheduler, /api/lifecycle) agree on
 * the probe shape.
 */
export async function probeAria2Reachable(
  client: Aria2Client | undefined,
): Promise<boolean | null> {
  if (!client) return null;
  try {
    await client.call("aria2.getVersion");
    return true;
  } catch {
    return false;
  }
}

/**
 * Run the configured disk-space gate against the resolved download
 * directory (or the process cwd as a fallback). Returns ok=false when
 * usage >= max_disk_usage_percent. Best-effort: any probe failure
 * yields ok=true (we don't poison the chip on a transient stat error).
 */
export async function probeDiskOk(
  declaration: Declaration,
): Promise<boolean> {
  try {
    const max = maxDiskPercent(declaration);
    const downloadDir = String(prefValue(declaration, "download_dir", "") ?? "");
    const probePath = downloadDir || process.cwd();
    const { statfsSync } = await import("node:fs");
    return checkDiskSpace({
      maxPercent: max,
      probe: () => {
        if (typeof statfsSync !== "function") return null;
        try {
          const fs = statfsSync(probePath);
          const total = Number(fs.blocks) * Number(fs.bsize);
          const free = Number(fs.bavail) * Number(fs.bsize);
          return { used: Math.max(0, total - free), total };
        } catch {
          return null;
        }
      },
    }).ok;
  } catch {
    return true;
  }
}
