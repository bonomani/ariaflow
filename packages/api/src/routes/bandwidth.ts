import {
  aria2,
  bandwidthConfigFrom,
  bandwidthUnits,
  runBandwidthProbe,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

export function registerBandwidthRoutes({ app, deps }: RouteContext): void {
  app.post("/api/bandwidth/probe", async (_req, reply) => {
    const declaration = await deps.declarationStore.load();
    const config = bandwidthConfigFrom(declaration);
    const runProbe = deps.runBandwidthProbe ?? runBandwidthProbe;
    const probeRec = await runProbe({ config });
    const downCap = probeRec.down_cap_mbps;
    const upCap = probeRec.up_cap_mbps;

    await deps.stateStore.update((s) => {
      (s as Record<string, unknown>).last_bandwidth_probe = probeRec as unknown as Record<
        string,
        unknown
      >;
      s.last_bandwidth_probe_at = Date.now() / 1000;
    });

    if (deps.aria2 && typeof probeRec.cap_bytes_per_sec === "number") {
      try {
        await aria2.setMaxOverallDownloadLimit(deps.aria2, probeRec.cap_bytes_per_sec);
      } catch {
        /* RPC failure is logged-only; the probe still applies locally */
      }
      const upCapBytes = Math.trunc(
        Number(probeRec.up_cap_mbps ?? 0) * bandwidthUnits.BYTES_PER_MEGABIT,
      );
      if (upCapBytes > 0) {
        try {
          await aria2.setMaxOverallUploadLimit(deps.aria2, upCapBytes);
        } catch {
          /* same */
        }
      }
    }

    await deps.actionLog.record({
      action: "probe",
      target: "bandwidth",
      outcome: probeRec.source === "networkquality" ? "changed" : "unchanged",
      reason: "manual_probe",
      detail: probeRec as unknown as Record<string, unknown>,
    });

    return reply.send({
      ok: true,
      probe: probeRec,
      config,
      interface_name: probeRec.interface_name ?? null,
      downlink_mbps: probeRec.downlink_mbps,
      uplink_mbps: probeRec.uplink_mbps ?? null,
      down_cap_mbps: downCap,
      up_cap_mbps: upCap,
      current_limit: probeRec.cap_bytes_per_sec ?? null,
      responsiveness_rpm: probeRec.responsiveness_rpm ?? null,
      source: probeRec.source,
    });
  });

  app.get("/api/bandwidth", async () => {
    const declaration = await deps.declarationStore.load();
    const state = await deps.stateStore.load();
    const config = bandwidthConfigFrom(declaration);
    const probe = (state.last_bandwidth_probe ?? null) as Record<string, unknown> | null;
    return withMeta("GET", "/api/bandwidth", {
      ok: true,
      config,
      last_probe: probe,
      last_probe_at: state.last_bandwidth_probe_at ?? null,
      // BG-21: surface probe fields at top level under the names the
      // dashboard's bwInterfaceText / bwSourceText / bwCurrentLimitText
      // helpers read.
      interface_name: probe?.interface_name ?? null,
      source: probe?.source ?? null,
      cap_mbps: probe?.cap_mbps ?? null,
      current_limit: probe?.cap_bytes_per_sec ?? null,
      downlink_mbps: probe?.downlink_mbps ?? null,
      uplink_mbps: probe?.uplink_mbps ?? null,
      down_cap_mbps: probe?.down_cap_mbps ?? null,
      up_cap_mbps: probe?.up_cap_mbps ?? null,
      responsiveness_rpm: probe?.responsiveness_rpm ?? null,
    });
  });
}
