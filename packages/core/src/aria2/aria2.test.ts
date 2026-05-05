import { describe, expect, it, vi } from "vitest";
import { Aria2Client, Aria2RpcError } from "./client.js";
import {
  addUri,
  changeGlobalOption,
  multicall,
  pause,
  setMaxOverallDownloadLimit,
  tellActive,
  tellStatus,
} from "./methods.js";

function makeFetch(handler: (req: { method: string; params: unknown[] }) => unknown) {
  return vi.fn(async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
    const result = handler(body);
    if (result instanceof Error) {
      return new Response(JSON.stringify({ jsonrpc: "2.0", id: "x", error: { code: 1, message: result.message } }));
    }
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  });
}

describe("Aria2Client.call", () => {
  it("posts JSON-RPC and returns the result field", async () => {
    const fetchImpl = makeFetch(({ method, params }) => {
      expect(method).toBe("aria2.tellStatus");
      expect(params).toEqual(["abc"]);
      return { gid: "abc", status: "active" };
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    expect(await tellStatus(c, "abc")).toEqual({ gid: "abc", status: "active" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("http://127.0.0.1:6800/jsonrpc");
  });

  it("prepends a token:secret param when configured", async () => {
    const fetchImpl = makeFetch(({ params }) => {
      expect(params[0]).toBe("token:s3cret");
      return "OK";
    });
    const c = new Aria2Client({
      fetch: fetchImpl as unknown as typeof fetch,
      secret: "s3cret",
    });
    await pause(c, "g1");
  });

  it("throws Aria2RpcError on error response", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ jsonrpc: "2.0", id: "x", error: { code: 1, message: "boom" } }),
        ),
    );
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    await expect(tellStatus(c, "x")).rejects.toBeInstanceOf(Aria2RpcError);
  });

  it("throws when result is missing", async () => {
    const fetchImpl = vi.fn(
      async () => new Response(JSON.stringify({ jsonrpc: "2.0", id: "x" })),
    );
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    await expect(tellStatus(c, "x")).rejects.toThrow(/missing 'result'/);
  });
});

describe("aria2 method wrappers", () => {
  it("addUri trims params when no options/position", async () => {
    const fetchImpl = makeFetch(({ method, params }) => {
      expect(method).toBe("aria2.addUri");
      expect(params).toEqual([["http://x/y"]]);
      return "GID1";
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    expect(await addUri(c, ["http://x/y"])).toBe("GID1");
  });

  it("addUri appends options + position when given", async () => {
    const fetchImpl = makeFetch(({ params }) => {
      expect(params).toEqual([["u"], { dir: "/d" }, 0]);
      return "GID2";
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    expect(await addUri(c, ["u"], { dir: "/d" }, 0)).toBe("GID2");
  });

  it("tellActive omits fields arg when not given", async () => {
    const fetchImpl = makeFetch(({ params }) => {
      expect(params).toEqual([]);
      return [];
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    expect(await tellActive(c)).toEqual([]);
  });

  it("setMaxOverallDownloadLimit goes through changeGlobalOption", async () => {
    const fetchImpl = makeFetch(({ method, params }) => {
      expect(method).toBe("aria2.changeGlobalOption");
      expect(params).toEqual([{ "max-overall-download-limit": "125000" }]);
      return "OK";
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    await setMaxOverallDownloadLimit(c, 125_000);
  });

  it("changeGlobalOption forwards the options dict", async () => {
    const fetchImpl = makeFetch(({ params }) => {
      expect(params).toEqual([{ "max-tries": "5" }]);
      return "OK";
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    await changeGlobalOption(c, { "max-tries": "5" });
  });

  it("multicall wraps entries in a single batch param", async () => {
    const fetchImpl = makeFetch(({ method, params }) => {
      expect(method).toBe("system.multicall");
      expect(params).toEqual([
        [
          { methodName: "aria2.tellActive", params: [] },
          { methodName: "aria2.tellStatus", params: ["g1"] },
        ],
      ]);
      return [];
    });
    const c = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    await multicall(c, [
      { methodName: "aria2.tellActive" },
      { methodName: "aria2.tellStatus", params: ["g1"] },
    ]);
  });
});
