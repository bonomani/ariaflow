import {
  probeDiskOk,
  summarizeQueue,
  toWireState,
  type Aria2Client,
  type QueueItemRecord,
  type ResolvedProbe,
  type ServerState,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { ServerDeps } from "../server.js";
import type { RouteContext, ServerMetrics } from "./_context.js";
import { computeSchedulerStatus } from "./_scheduler_status.js";

interface Identity {
  reachable: boolean;
  pid: number;
  version: string;
  error: null;
}

/**
 * BG-19: identity sub-object the dashboard reads to populate header
 * pills + the offline-state gate. Always set even when the server is
 * the one answering (reachable=true is structurally implied — the
 * frontend's offline detector treats reachable=false as the trigger).
 */
function buildIdentity(deps: ServerDeps): Identity {
  return {
    reachable: true,
    pid: process.pid,
    version: deps.version ?? "0.0.0",
    error: null,
  };
}

/**
 * BG-24: server metrics for the Developer-tab chips. disk_ok is
 * resolved from max_disk_usage_percent + checkDiskSpace() so a
 * low-disk warning surfaces here too.
 */
async function buildHealth(deps: ServerDeps, metrics: ServerMetrics) {
  const diskOk = await probeDiskOk(await deps.declarationStore.load());
  return {
    uptime_seconds: process.uptime(),
    requests_total: metrics.requestsTotal,
    errors_total: metrics.errorsTotal,
    sse_clients: metrics.sseClients,
    bytes_received_total: metrics.bytesReceivedTotal,
    bytes_sent_total: metrics.bytesSentTotal,
    disk_ok: diskOk,
  };
}

/**
 * BG-25 sub-issue: lift the live bandwidth probe summary to a top-level
 * `bandwidth` key (mirroring /api/bandwidth's BG-21 shape) so the
 * dashboard's Cap chip works on the Dashboard tab without first
 * visiting Bandwidth.
 */
function buildBandwidthBlock(
  state: ServerState,
): (ResolvedProbe & { last_probe_at: number | null }) | null {
  const probe = state.last_bandwidth_probe ?? null;
  if (!probe) return null;
  return { ...probe, last_probe_at: state.last_bandwidth_probe_at ?? null };
}

/**
 * BG-30 #5: derive active_gid / active_url from aria2.tellActive at
 * read time — the stamped state.active_gid stays as a fallback when
 * the daemon is unreachable, but the live tellActive answer wins so
 * a crash never leaves a phantom gid spotlit on the chip.
 */
async function deriveLiveActive(
  state: ServerState,
  items: QueueItemRecord[],
  aria2: Aria2Client | undefined,
): Promise<{ active_gid: string | null; active_url: string | null }> {
  let liveActiveGid: string | null = (state.active_gid as string | null) ?? null;
  let liveActiveUrl: string | null = (state.active_url as string | null) ?? null;
  if (!aria2) return { active_gid: liveActiveGid, active_url: liveActiveUrl };
  try {
    const infos = (await aria2.call<unknown[]>("aria2.tellActive")) as Array<
      Record<string, unknown>
    >;
    if (infos.length === 0) return { active_gid: null, active_url: null };
    const top = infos[0]!;
    const gid = typeof top.gid === "string" ? top.gid : null;
    liveActiveGid = gid;
    const match = gid ? items.find((i) => i.gid === gid) : null;
    liveActiveUrl = match ? match.url ?? null : liveActiveUrl;
  } catch {
    /* aria2 unreachable — keep stamped fallback */
  }
  return { active_gid: liveActiveGid, active_url: liveActiveUrl };
}

function applyFilters(
  items: QueueItemRecord[],
  state: ServerState,
  statusFilter: string,
  sessionFilter: string,
): QueueItemRecord[] {
  let filtered = items;
  if (statusFilter) {
    const allowed = new Set(
      statusFilter.split(",").map((s) => s.trim()).filter(Boolean),
    );
    filtered = filtered.filter((i) => allowed.has(String(i.status ?? "")));
  }
  if (sessionFilter === "current") {
    filtered = filtered.filter((i) => i.session_id === state.session_id);
  } else if (sessionFilter) {
    filtered = filtered.filter((i) => i.session_id === sessionFilter);
  }
  return filtered;
}

export function registerStatusRoute({ app, deps, metrics }: RouteContext): void {
  app.get<{ Querystring: { status?: string; session?: string } }>(
    "/api/status",
    async (req) => {
      const items = await deps.queueStore.load();
      const state = await deps.stateStore.load();
      const filtered = applyFilters(
        items,
        state,
        (req.query?.status ?? "").trim(),
        (req.query?.session ?? "").trim(),
      );

      const [health, live, scheduler] = await Promise.all([
        buildHealth(deps, metrics),
        deriveLiveActive(state, items, deps.aria2),
        computeSchedulerStatus(deps, state),
      ]);

      // BG-33: `dispatch_paused` is the canonical scheduler-pause field
      // (disambiguates from item-level `paused`). toWireState strips
      // the internal `paused` and stamps `dispatch_paused`.
      const stateOut = {
        ...toWireState(state),
        active_gid: live.active_gid,
        active_url: live.active_url,
        scheduler_status: scheduler.status,
        wait_reason: scheduler.wait_reason,
      };

      return withMeta("GET", "/api/status", {
        ok: true,
        "ariaflow-server": buildIdentity(deps),
        health,
        items: filtered,
        summary: summarizeQueue(filtered),
        state: stateOut,
        bandwidth: buildBandwidthBlock(state),
        _rev: Number(state._rev ?? 0),
      });
    },
  );
}
