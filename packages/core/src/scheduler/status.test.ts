import { describe, expect, it } from "vitest";
import { deriveSchedulerStatus, deriveWaitReason } from "./status.js";
import type { ServerState } from "../storage/state.js";
import type { QueueItemRecord } from "../queue/types.js";

const baseState = (): ServerState => ({
  paused: false,
  active_gid: null,
  active_url: null,
  running: false,
  session_id: null,
  session_started_at: null,
  session_last_seen_at: null,
  session_closed_at: null,
  session_closed_reason: null,
});

describe("deriveSchedulerStatus", () => {
  it("returns 'stopped' when scheduler_intent is undefined (legacy state)", () => {
    expect(deriveSchedulerStatus(baseState())).toBe("stopped");
  });

  it("returns 'stopped' when intent='stopped' regardless of running flag", () => {
    expect(
      deriveSchedulerStatus({ ...baseState(), scheduler_intent: "stopped", running: true }),
    ).toBe("stopped");
  });

  it("returns 'starting' when intent='running' and no session has been opened yet (bootstrap)", () => {
    expect(
      deriveSchedulerStatus({
        ...baseState(),
        scheduler_intent: "running",
        running: false,
        // session_id stays null — loop's first tick hasn't run.
      }),
    ).toBe("starting");
  });

  it("returns 'idle' when intent='running' + running=false but a session is open (drained loop)", () => {
    // runSchedulerLoop sets running=false on a clean drain/max_iterations
    // exit. The session stays open until /api/sessions/close. The next
    // /api/downloads add will re-kick the loop.
    expect(
      deriveSchedulerStatus({
        ...baseState(),
        scheduler_intent: "running",
        running: false,
        session_id: "abc-123",
        session_started_at: "2026-05-05T00:00:00Z",
      }),
    ).toBe("idle");
  });

  it("returns 'paused' when running and dispatch is paused", () => {
    expect(
      deriveSchedulerStatus({
        ...baseState(),
        scheduler_intent: "running",
        running: true,
        paused: true,
      }),
    ).toBe("paused");
  });

  it("returns 'running' when running with an active_gid", () => {
    expect(
      deriveSchedulerStatus({
        ...baseState(),
        scheduler_intent: "running",
        running: true,
        active_gid: "gid-1",
      }),
    ).toBe("running");
  });

  it("returns 'idle' when running but no active_gid", () => {
    expect(
      deriveSchedulerStatus({
        ...baseState(),
        scheduler_intent: "running",
        running: true,
      }),
    ).toBe("idle");
  });

  it("BG-50: returns 'paused' when paused even if loop is drained (running=false, session open)", () => {
    expect(
      deriveSchedulerStatus({
        ...baseState(),
        scheduler_intent: "running",
        running: false,
        paused: true,
        session_id: "abc-123",
        session_started_at: "2026-05-06T00:00:00Z",
      }),
    ).toBe("paused");
  });
});

const idleInputs = (overrides: Partial<Parameters<typeof deriveWaitReason>[0]> = {}) => ({
  status: "idle" as const,
  aria2Reachable: true,
  preflightOk: true,
  diskOk: true,
  lastBandwidthProbeAt: 1_000_000,
  bandwidthProbeMaxAgeSeconds: 600,
  items: [] as readonly QueueItemRecord[],
  now: 1_000_100,
  ...overrides,
});

describe("deriveWaitReason", () => {
  it("returns null when status is not 'idle'", () => {
    for (const status of ["stopped", "starting", "running", "paused"] as const) {
      expect(deriveWaitReason(idleInputs({ status }))).toBeNull();
    }
  });

  it("returns 'aria2_unreachable' first when aria2 RPC failed", () => {
    expect(
      deriveWaitReason(
        idleInputs({ aria2Reachable: false, preflightOk: false, diskOk: false }),
      ),
    ).toBe("aria2_unreachable");
  });

  it("returns 'preflight_blocked' when preflight failed (and aria2 ok)", () => {
    expect(deriveWaitReason(idleInputs({ preflightOk: false }))).toBe("preflight_blocked");
  });

  it("returns 'disk_full' when disk-space gate failed", () => {
    expect(deriveWaitReason(idleInputs({ diskOk: false }))).toBe("disk_full");
  });

  it("returns 'bandwidth_probe_pending' when probe is stale or never run (with work in queue)", () => {
    // BG-47: queue_empty wins over bandwidth_probe_pending, so these
    // checks need at least one pending item to isolate the probe path.
    const pending = [
      { id: "1", url: "http://h/a", status: "queued" } as unknown as QueueItemRecord,
    ];
    expect(
      deriveWaitReason(idleInputs({ lastBandwidthProbeAt: null, items: pending })),
    ).toBe("bandwidth_probe_pending");
    expect(
      deriveWaitReason(idleInputs({ lastBandwidthProbeAt: 0, items: pending })),
    ).toBe("bandwidth_probe_pending");
    // 700s > 600s threshold
    expect(
      deriveWaitReason(
        idleInputs({ lastBandwidthProbeAt: 999_400, now: 1_000_100, items: pending }),
      ),
    ).toBe("bandwidth_probe_pending");
  });

  it("BG-47: returns 'queue_empty' even when probe is stale, since the probe is irrelevant on an empty queue", () => {
    expect(
      deriveWaitReason(idleInputs({ items: [], lastBandwidthProbeAt: null })),
    ).toBe("queue_empty");
  });

  it("returns 'queue_empty' when everything else is fine but no pending items", () => {
    expect(deriveWaitReason(idleInputs({ items: [] }))).toBe("queue_empty");
  });

  it("returns null when there is at least one pending item and all gates pass", () => {
    const items = [
      { id: "1", url: "http://h/a", status: "queued" } as unknown as QueueItemRecord,
    ];
    expect(deriveWaitReason(idleInputs({ items }))).toBeNull();
  });

  it("ignores terminal statuses when checking for pending work", () => {
    const items = [
      { id: "1", url: "http://h/a", status: "complete" } as unknown as QueueItemRecord,
      { id: "2", url: "http://h/b", status: "removed" } as unknown as QueueItemRecord,
    ];
    expect(deriveWaitReason(idleInputs({ items }))).toBe("queue_empty");
  });
});
