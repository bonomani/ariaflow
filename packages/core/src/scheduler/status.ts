import type { QueueItemRecord } from "../queue/types.js";
import type { ServerState } from "../storage/state.js";

export type SchedulerStatus =
  | "stopped"
  | "starting"
  | "idle"
  | "running"
  | "paused";

export type WaitReason =
  | "queue_empty"
  | "aria2_unreachable"
  | "preflight_blocked"
  | "disk_full"
  | "bandwidth_probe_pending"
  | null;

const PENDING_STATUSES = new Set(["queued", "waiting", "active"]);

/**
 * Derive the operator-facing scheduler status from the persisted state.
 *
 * Truth table:
 *   intent=stopped                                → "stopped"
 *   intent=running, no session yet                → "starting"
 *     (genuine bootstrap window: operator hit start but the loop's
 *      first tick hasn't opened a session)
 *   intent=running, running=false, session open   → "idle"
 *     (loop drained — runSchedulerLoop sets running=false on a clean
 *      drain/max_iterations exit; the operator still wants it
 *      running, so the next /api/downloads add will re-kick it)
 *   intent=running, running=true, paused=true     → "paused"
 *   intent=running, running=true, active_gid      → "running"
 *   intent=running, running=true, !active_gid     → "idle"
 *
 * `scheduler_intent` is undefined on legacy on-disk state files; treat
 * undefined as "stopped" (the documented default).
 */
export function deriveSchedulerStatus(state: ServerState): SchedulerStatus {
  const intent = state.scheduler_intent ?? "stopped";
  if (intent === "stopped") return "stopped";
  if (!state.running) {
    // Loop has run at least once iff a session was opened. If the
    // session is still open (or a closed session is present), the loop
    // ran and exited cleanly — treat as idle, not starting.
    const hasOpenSession = Boolean(state.session_id);
    return hasOpenSession ? "idle" : "starting";
  }
  if (state.paused) return "paused";
  return state.active_gid ? "running" : "idle";
}

/**
 * Inputs for wait-reason classification. Each axis is an already-resolved
 * boolean / nullable so this stays a pure function — the caller spawns
 * the actual probes (aria2 RPC, preflight evaluation, disk check, ...)
 * and feeds them in. That keeps tests free of fakes.
 */
export interface WaitReasonInputs {
  status: SchedulerStatus;
  aria2Reachable: boolean | null;
  preflightOk: boolean;
  diskOk: boolean;
  /** Epoch seconds; null if no probe has run. */
  lastBandwidthProbeAt: number | null;
  bandwidthProbeMaxAgeSeconds: number;
  items: readonly QueueItemRecord[];
  now?: number;
}

/**
 * Classify why the scheduler is idle. Returns null when the scheduler is
 * actively dispatching, paused, stopped, or starting — wait_reason is
 * meaningful only in the "idle" state per BG-40.
 *
 * Order of checks: hard blockers (aria2/preflight/disk) first, then
 * `queue_empty` BEFORE `bandwidth_probe_pending` per BG-47 — an empty
 * queue makes the probe state irrelevant, since the probe only runs
 * when there's work to schedule. Reporting "probe pending" on an
 * empty queue is misleading.
 */
export function deriveWaitReason(input: WaitReasonInputs): WaitReason {
  if (input.status !== "idle") return null;
  if (input.aria2Reachable === false) return "aria2_unreachable";
  if (!input.preflightOk) return "preflight_blocked";
  if (!input.diskOk) return "disk_full";
  const hasPending = input.items.some((i) =>
    PENDING_STATUSES.has(String(i.status ?? "")),
  );
  if (!hasPending) return "queue_empty";
  const now = input.now ?? Date.now() / 1000;
  const probeAt = input.lastBandwidthProbeAt ?? 0;
  const probeStale =
    probeAt <= 0 || now - probeAt > input.bandwidthProbeMaxAgeSeconds;
  if (probeStale) return "bandwidth_probe_pending";
  return null;
}
