import type { Aria2Client } from "./client.js";
import {
  setMaxOverallDownloadLimit,
  setMaxOverallUploadLimit,
  setMaxDownloadLimit,
  tellActive,
} from "./methods.js";
import { BYTES_PER_MEGABIT } from "../bandwidth/units.js";
import type { ResolvedProbe } from "../bandwidth/run.js";

/**
 * BG-52/BG-53: apply a fresh probe to aria2 — set the global download
 * cap, walk every active gid and refresh per-download limit so in-flight
 * transfers track the new cap (aria2 enforces min(per-download, global),
 * so a stale per-download silently throttles below the new global), and
 * apply the upload cap when the probe carries one.
 *
 * All RPC failures are swallowed so a single bad gid or RPC hiccup
 * doesn't abort the rest of the pass. Caller already updated state /
 * recorded the audit-log entry; this helper is purely the aria2 side.
 */
export async function applyBandwidthCap(
  client: Aria2Client,
  probe: ResolvedProbe,
): Promise<void> {
  if (typeof probe.cap_bytes_per_sec !== "number") return;
  const cap = probe.cap_bytes_per_sec;
  try {
    await setMaxOverallDownloadLimit(client, cap);
  } catch {
    /* RPC failure is logged-only; the probe still applies locally */
  }
  try {
    const active = await tellActive(client, ["gid"]);
    for (const row of active) {
      const gid = (row as { gid?: string }).gid;
      if (!gid) continue;
      try {
        await setMaxDownloadLimit(client, gid, cap);
      } catch {
        /* per-gid failures don't block the rest */
      }
    }
  } catch {
    /* tellActive failed — global cap still applied above */
  }
  const upCapBytes = Math.trunc(Number(probe.up_cap_mbps ?? 0) * BYTES_PER_MEGABIT);
  if (upCapBytes > 0) {
    try {
      await setMaxOverallUploadLimit(client, upCapBytes);
    } catch {
      /* same */
    }
  }
}
