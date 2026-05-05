import { describe, expect, it, vi } from "vitest";
import { checkDiskSpace, maxDiskPercent } from "./helpers.js";
import { getActiveProgress } from "./progress.js";
import { Aria2Client } from "../aria2/client.js";
import { defaultDeclaration } from "../contracts/declaration.js";
import type { ServerState } from "../storage/state.js";

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
