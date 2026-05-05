import { prefValue, scheduler as schedulerHelpers, summarizeQueue } from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";
import { computeSchedulerStatus } from "./_scheduler_status.js";

export function registerStatusRoute({ app, deps, metrics }: RouteContext): void {
  app.get<{ Querystring: { status?: string; session?: string } }>(
    "/api/status",
    async (req) => {
      const items = await deps.queueStore.load();
      const state = await deps.stateStore.load();
      const statusFilter = (req.query?.status ?? "").trim();
      const sessionFilter = (req.query?.session ?? "").trim();
      let filtered = items;
      if (statusFilter) {
        const allowed = new Set(statusFilter.split(",").map((s) => s.trim()).filter(Boolean));
        filtered = filtered.filter((i) => allowed.has(String(i.status ?? "")));
      }
      if (sessionFilter === "current") {
        filtered = filtered.filter((i) => i.session_id === state.session_id);
      } else if (sessionFilter) {
        filtered = filtered.filter((i) => i.session_id === sessionFilter);
      }
      // BG-19: identity sub-object the dashboard reads to populate
      // header pills + the offline-state gate. Always set even when the
      // server is the one answering (reachable=true is structurally
      // implied — the frontend's offline detector treats reachable=false
      // as the trigger).
      const identity = {
        reachable: true,
        pid: process.pid,
        version: deps.version ?? "0.0.0",
        error: null,
      };

      // BG-24: server metrics for the Developer-tab chips. disk_ok is
      // resolved from the configured max_disk_usage_percent pref +
      // checkDiskSpace() so a low-disk warning surfaces here too.
      let diskOk = true;
      try {
        const declaration = await deps.declarationStore.load();
        const max = schedulerHelpers.maxDiskPercent(declaration);
        const downloadDirPref = String(
          prefValue(declaration, "download_dir", "") ?? "",
        );
        const probePath = downloadDirPref || process.cwd();
        const { statfsSync } = await import("node:fs");
        diskOk = schedulerHelpers.checkDiskSpace({
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
        // Best-effort — unknown disk state shouldn't poison the chip.
        diskOk = true;
      }

      const health = {
        uptime_seconds: process.uptime(),
        requests_total: metrics.requestsTotal,
        errors_total: metrics.errorsTotal,
        sse_clients: metrics.sseClients,
        bytes_received_total: metrics.bytesReceivedTotal,
        bytes_sent_total: metrics.bytesSentTotal,
        disk_ok: diskOk,
      };

      // BG-25 sub-issue: lift the live bandwidth probe summary to a
      // top-level `bandwidth` key (mirroring /api/bandwidth's BG-21
      // shape) so the dashboard's Cap chip works on the Dashboard tab
      // without first visiting Bandwidth.
      const probe = (state.last_bandwidth_probe ?? null) as Record<string, unknown> | null;
      const bandwidth = probe
        ? { ...probe, last_probe_at: state.last_bandwidth_probe_at ?? null }
        : null;

      // BG-30 #5: derive active_gid / active_url from aria2.tellActive
      // at read time — the stamped state.active_gid stays as a fallback
      // when the daemon is unreachable, but the live tellActive answer
      // wins so a crash never leaves a phantom gid spotlit on the chip.
      let liveActiveGid: string | null = (state.active_gid as string | null) ?? null;
      let liveActiveUrl: string | null = (state.active_url as string | null) ?? null;
      if (deps.aria2) {
        try {
          const infos = (await deps.aria2.call<unknown[]>("aria2.tellActive")) as Array<
            Record<string, unknown>
          >;
          if (infos.length > 0) {
            const top = infos[0]!;
            const gid = typeof top.gid === "string" ? top.gid : null;
            liveActiveGid = gid;
            const match = gid ? items.find((i) => i.gid === gid) : null;
            liveActiveUrl = match ? match.url ?? null : liveActiveUrl;
          } else {
            liveActiveGid = null;
            liveActiveUrl = null;
          }
        } catch {
          /* aria2 unreachable — keep stamped fallback */
        }
      }

      // BG-33: `dispatch_paused` is the canonical scheduler-pause field
      // (disambiguates from item-level `paused`). Internal storage keeps
      // `state.paused` as the field name; we do not surface it.
      const dispatchPaused = Boolean(state.paused);

      // BG-40: scheduler_status + wait_reason on /api/status mirror the
      // /api/scheduler view so the dashboard's System Health card
      // doesn't need a second fetch.
      const { status: schedulerStatus, wait_reason } =
        await computeSchedulerStatus(deps, state);

      const summary = summarizeQueue(filtered);

      const { paused: _legacyPaused, ...stateRest } = state;
      void _legacyPaused;
      const stateOut: Record<string, unknown> = {
        ...stateRest,
        active_gid: liveActiveGid,
        active_url: liveActiveUrl,
        dispatch_paused: dispatchPaused,
        scheduler_status: schedulerStatus,
        wait_reason,
      };

      const payload: Record<string, unknown> = {
        ok: true,
        "ariaflow-server": identity,
        health,
        items: filtered,
        summary,
        state: stateOut,
        bandwidth,
        _rev: Number(state._rev ?? 0),
      };
      return withMeta("GET", "/api/status", payload);
    },
  );
}
