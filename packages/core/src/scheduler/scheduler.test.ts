import { describe, expect, it, vi } from "vitest";
import {
  autoPreflightOnRun,
  checkDiskSpace,
  desiredState,
  maxDiskPercent,
  reinjectStatus,
  rpcPollFailureMessage,
} from "./helpers.js";
import { getActiveProgress } from "./progress.js";
import { Aria2Client } from "../aria2/client.js";
import { defaultDeclaration } from "../contracts/declaration.js";
import type { ServerState } from "../storage/state.js";

describe("rpcPollFailureMessage", () => {
  it("prefers the error message text", () => {
    expect(rpcPollFailureMessage(new Error("custom"))).toBe("custom");
  });
  it("classifies timeout-named errors", () => {
    const err = new Error("");
    err.name = "TimeoutError";
    expect(rpcPollFailureMessage(err)).toBe("aria2 status RPC timed out");
  });
  it("classifies connection-named errors", () => {
    const err = new Error("");
    err.name = "ConnectionRefusedError";
    expect(rpcPollFailureMessage(err)).toBe("aria2 status RPC connection failed");
  });
  it("falls back to a generic message", () => {
    expect(rpcPollFailureMessage("oops")).toBe("aria2 status RPC failed");
  });
});

describe("desiredState / reinjectStatus", () => {
  it.each([
    [{ desired_state: "running" }, "running"],
    [{ desired_state: "paused" }, "paused"],
    [{ desired_state: "  RUNNING " }, "running"],
    [{ status: "paused" }, "paused"],
    [{ status: "queued" }, "running"],
    [{}, "running"],
  ] as const)("desiredState(%j) -> %s", (item, expected) => {
    expect(desiredState({ id: "x", url: "u", ...item })).toBe(expected);
  });

  it("reinjectStatus picks paused vs queued from desired", () => {
    expect(reinjectStatus({ id: "x", url: "u", desired_state: "paused" })).toBe("paused");
    expect(reinjectStatus({ id: "x", url: "u", desired_state: "running" })).toBe("queued");
  });
});

describe("checkDiskSpace", () => {
  it("returns ok=true with 0 when threshold is 0", () => {
    expect(
      checkDiskSpace({ maxPercent: 0, probe: () => ({ used: 95, total: 100 }) }),
    ).toEqual({ ok: true, percentUsed: 0 });
  });
  it("ok=false when usage >= threshold", () => {
    expect(
      checkDiskSpace({ maxPercent: 90, probe: () => ({ used: 95, total: 100 }) }),
    ).toEqual({ ok: false, percentUsed: 95 });
  });
  it("ok=true when probe fails", () => {
    expect(checkDiskSpace({ maxPercent: 90, probe: () => null })).toEqual({
      ok: true,
      percentUsed: 0,
    });
  });
  it("rounds percent to one decimal", () => {
    expect(
      checkDiskSpace({ maxPercent: 90, probe: () => ({ used: 333, total: 1000 }) }).percentUsed,
    ).toBe(33.3);
  });
});

describe("declaration prefs", () => {
  it("autoPreflightOnRun defaults to false", () => {
    expect(autoPreflightOnRun(defaultDeclaration())).toBe(false);
  });
  it("maxDiskPercent reads from the declaration", () => {
    expect(maxDiskPercent(defaultDeclaration())).toBe(90);
  });
});

describe("getActiveProgress", () => {
  const baseState: ServerState = {
    paused: false,
    active_gid: "G1",
    active_url: "http://x",
    running: true,
    session_id: null,
    session_started_at: null,
    session_last_seen_at: null,
    session_closed_at: null,
    session_closed_reason: null,
  };

  it("returns null when no active_gid", async () => {
    const c = new Aria2Client({ fetch: vi.fn() as unknown as typeof fetch });
    expect(await getActiveProgress(c, { ...baseState, active_gid: null })).toBeNull();
  });

  it("computes percent and forwards speeds/lengths", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            jsonrpc: "2.0",
            id: "x",
            result: {
              gid: "G1",
              status: "active",
              totalLength: "1000",
              completedLength: "250",
              downloadSpeed: "42",
            },
          }),
        ),
    );
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    const p = await getActiveProgress(c, baseState);
    expect(p).toMatchObject({
      gid: "G1",
      url: "http://x",
      status: "active",
      download_speed: 42,
      completed_length: 250,
      total_length: 1000,
      percent: 25,
    });
  });

  it("returns an error shape on RPC failure", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("boom");
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    const p = await getActiveProgress(c, baseState);
    expect(p).toMatchObject({ gid: "G1", url: "http://x", error: "boom" });
  });
});
