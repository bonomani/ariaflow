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

  it("returns 'starting' when intent='running' but loop hasn't flipped running yet", () => {
    expect(
      deriveSchedulerStatus({ ...baseState(), scheduler_intent: "running", running: false }),
    ).toBe("starting");
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

  it("returns 'bandwidth_probe_pending' when probe is stale or never run", () => {
    expect(deriveWaitReason(idleInputs({ lastBandwidthProbeAt: null }))).toBe(
      "bandwidth_probe_pending",
    );
    expect(deriveWaitReason(idleInputs({ lastBandwidthProbeAt: 0 }))).toBe(
      "bandwidth_probe_pending",
    );
    // 700s > 600s threshold
    expect(
      deriveWaitReason(idleInputs({ lastBandwidthProbeAt: 999_400, now: 1_000_100 })),
    ).toBe("bandwidth_probe_pending");
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
