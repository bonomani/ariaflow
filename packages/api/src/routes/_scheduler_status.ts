import {
  deriveSchedulerStatus,
  deriveWaitReason,
  evaluatePreflight,
  prefValue,
  probeAria2Reachable,
  probeDiskOk,
  type SchedulerStatus,
  type ServerState,
  type WaitReason,
} from "@ariaflow/core";
import type { ServerDeps } from "../server.js";

interface SchedulerStatusBlock {
  status: SchedulerStatus;
  wait_reason: WaitReason;
}

/**
 * Compute the {status, wait_reason} pair surfaced on /api/scheduler and
 * mirrored on /api/status.state. status is pure; wait_reason needs probes
 * (aria2 RPC, preflight evaluation, disk space, bandwidth-probe age),
 * but only when status === "idle" — every other status returns
 * wait_reason: null without paying for the probes.
 */
export async function computeSchedulerStatus(
  deps: ServerDeps,
  state: ServerState,
): Promise<SchedulerStatusBlock> {
  const status = deriveSchedulerStatus(state);
  if (status !== "idle") {
    return { status, wait_reason: null };
  }

  const declaration = await deps.declarationStore.load();
  const items = await deps.queueStore.load();
  const aria2Reachable = await probeAria2Reachable(deps.aria2);

  const preflight = evaluatePreflight(declaration, {
    aria2_available: aria2Reachable === true,
    queue_readable: true,
    paused: state.paused,
  });

  const diskOk = await probeDiskOk(declaration);

  const probeIntervalSeconds = Math.max(
    30,
    Number(prefValue(declaration, "bandwidth_probe_interval_seconds", 180)) || 180,
  );
  // Probe is "pending" if older than ~3x the probe interval (so a
  // briefly-overdue probe doesn't flip the badge to a fault state).
  const bandwidthProbeMaxAgeSeconds = probeIntervalSeconds * 3;

  const wait_reason = deriveWaitReason({
    status,
    aria2Reachable,
    preflightOk: preflight.status === "pass",
    diskOk,
    lastBandwidthProbeAt: Number(state.last_bandwidth_probe_at ?? 0) || null,
    bandwidthProbeMaxAgeSeconds,
    items,
  });

  return { status, wait_reason };
}
