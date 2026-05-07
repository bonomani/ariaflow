import { describe, expect, it, vi } from "vitest";
import { Aria2Client } from "./client.js";
import { applyBandwidthCap } from "./cap.js";
import type { ResolvedProbe } from "../bandwidth/run.js";

interface Captured {
  method: string;
  params: unknown[];
}

function client(replies: Record<string, unknown> = {}): {
  client: Aria2Client;
  calls: Captured[];
} {
  const calls: Captured[] = [];
  const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as Captured;
    calls.push(body);
    const result = Object.prototype.hasOwnProperty.call(replies, body.method)
      ? replies[body.method]
      : "OK";
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result }),
    );
  });
  return {
    client: new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch }),
    calls,
  };
}

const probe = (over: Partial<ResolvedProbe> = {}): ResolvedProbe =>
  ({
    cap_bytes_per_sec: 1_000_000,
    interval_seconds: 60,
    down_cap_mbps: null,
    up_cap_mbps: null,
    source: "networkquality",
    ...over,
  }) as ResolvedProbe;

describe("applyBandwidthCap (BG-52/53)", () => {
  it("returns early when cap_bytes_per_sec is missing", async () => {
    const { client: c, calls } = client();
    const p = probe();
    delete (p as { cap_bytes_per_sec?: number }).cap_bytes_per_sec;
    await applyBandwidthCap(c, p);
    expect(calls).toEqual([]);
  });

  it("sets the global download cap", async () => {
    const { client: c, calls } = client({ "aria2.tellActive": [] });
    await applyBandwidthCap(c, probe({ cap_bytes_per_sec: 2_000_000 }));
    const global = calls.find((c) => c.method === "aria2.changeGlobalOption");
    expect(global).toBeDefined();
    expect(global!.params).toEqual([{ "max-overall-download-limit": "2000000" }]);
  });

  it("BG-53: refreshes per-gid max-download-limit on every active transfer", async () => {
    const { client: c, calls } = client({
      "aria2.tellActive": [{ gid: "G1" }, { gid: "G2" }],
    });
    await applyBandwidthCap(c, probe({ cap_bytes_per_sec: 500_000 }));
    const perGid = calls.filter((c) => c.method === "aria2.changeOption");
    expect(perGid).toHaveLength(2);
    expect(perGid[0]!.params).toEqual(["G1", { "max-download-limit": "500000" }]);
    expect(perGid[1]!.params).toEqual(["G2", { "max-download-limit": "500000" }]);
  });

  it("skips per-gid refresh when tellActive returns no rows", async () => {
    const { client: c, calls } = client({ "aria2.tellActive": [] });
    await applyBandwidthCap(c, probe({ cap_bytes_per_sec: 1_000 }));
    expect(calls.find((c) => c.method === "aria2.changeOption")).toBeUndefined();
  });

  it("sets the upload cap when up_cap_mbps > 0", async () => {
    const { client: c, calls } = client({ "aria2.tellActive": [] });
    await applyBandwidthCap(c, probe({ cap_bytes_per_sec: 1_000_000, up_cap_mbps: 8 }));
    // Two changeGlobalOption calls expected: download then upload.
    const globals = calls.filter((c) => c.method === "aria2.changeGlobalOption");
    expect(globals).toHaveLength(2);
    expect(globals[0]!.params).toEqual([{ "max-overall-download-limit": "1000000" }]);
    expect(globals[1]!.params).toEqual([{ "max-overall-upload-limit": "1000000" }]);
  });

  it("does not set upload cap when up_cap_mbps is 0 / null", async () => {
    const { client: c, calls } = client({ "aria2.tellActive": [] });
    await applyBandwidthCap(c, probe({ up_cap_mbps: 0 }));
    const globals = calls.filter((c) => c.method === "aria2.changeGlobalOption");
    expect(globals).toHaveLength(1);
  });

  it("survives RPC failure on tellActive (global cap still applied)", async () => {
    const calls: Captured[] = [];
    const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(init!.body as string) as Captured;
      calls.push(body);
      if (body.method === "aria2.tellActive") {
        return new Response(
          JSON.stringify({
            jsonrpc: "2.0",
            id: "x",
            error: { code: -32000, message: "boom" },
          }),
        );
      }
      return new Response(JSON.stringify({ jsonrpc: "2.0", id: "x", result: "OK" }));
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    await applyBandwidthCap(c, probe({ cap_bytes_per_sec: 1_000 }));
    expect(calls.find((c) => c.method === "aria2.changeGlobalOption")).toBeDefined();
  });
});
