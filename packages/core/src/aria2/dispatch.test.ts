import { describe, expect, it, vi } from "vitest";
import { Aria2Client } from "./client.js";
import { dispatchDownload, dispatchPrefsFrom } from "./dispatch.js";
import { defaultDeclaration } from "../contracts/declaration.js";
import type { QueueItemRecord } from "../queue/types.js";

interface Captured {
  method: string;
  params: unknown[];
}

function client(reply: (c: Captured) => unknown): { client: Aria2Client; calls: Captured[] } {
  const calls: Captured[] = [];
  const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as Captured;
    calls.push(body);
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result: reply(body) }),
    );
  });
  return {
    client: new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch }),
    calls,
  };
}

const baseItem: QueueItemRecord = {
  id: "i1",
  url: "http://h/file.iso",
  mode: "http",
  output: "file.iso",
};

describe("dispatchPrefsFrom", () => {
  it("reads aria2_max_tries / aria2_retry_wait from the declaration", () => {
    expect(dispatchPrefsFrom(defaultDeclaration())).toEqual({
      max_tries: 5,
      retry_wait: 10,
    });
  });
});

describe("dispatchDownload", () => {
  const prefs = { max_tries: 5, retry_wait: 10 };

  it("plain http -> aria2.addUri with default options", async () => {
    const { client: c, calls } = client(() => "GID-HTTP");
    const gid = await dispatchDownload(c, baseItem, { capBytesPerSec: 1_000_000, prefs });
    expect(gid).toBe("GID-HTTP");
    expect(calls).toHaveLength(1);
    expect(calls[0]!.method).toBe("aria2.addUri");
    const [uris, options] = calls[0]!.params as [string[], Record<string, string>];
    expect(uris).toEqual(["http://h/file.iso"]);
    expect(options).toMatchObject({
      "max-download-limit": "1000000",
      "allow-overwrite": "true",
      continue: "true",
      "max-tries": "5",
      "retry-wait": "10",
      out: "file.iso",
    });
    expect(options["pause-metadata"]).toBeUndefined();
  });

  it("magnet/torrent/metalink modes set pause-metadata", async () => {
    for (const mode of ["torrent", "metalink", "magnet"] as const) {
      const { client: c, calls } = client(() => "GID");
      await dispatchDownload(
        c,
        { ...baseItem, mode, url: "http://h/x." + (mode === "magnet" ? "torrent" : mode) },
        { capBytesPerSec: 0, prefs },
      );
      const [, options] = calls[0]!.params as [string[], Record<string, string>];
      expect(options["pause-metadata"]).toBe("true");
    }
  });

  it("mode=mirror dedups and merges url + mirrors", async () => {
    const { client: c, calls } = client(() => "GID-M");
    await dispatchDownload(
      c,
      { ...baseItem, mode: "mirror", mirrors: ["http://h/file.iso", "http://b/file.iso"] },
      { capBytesPerSec: 0, prefs },
    );
    const [uris] = calls[0]!.params as [string[]];
    expect(uris).toEqual(["http://h/file.iso", "http://b/file.iso"]);
  });

  it("mode=torrent_data calls aria2.addTorrent and forces pause-metadata", async () => {
    const { client: c, calls } = client(() => "GID-T");
    const gid = await dispatchDownload(
      c,
      { ...baseItem, mode: "torrent_data", torrent_data: "BASE64" },
      { capBytesPerSec: 0, prefs },
    );
    expect(gid).toBe("GID-T");
    expect(calls[0]!.method).toBe("aria2.addTorrent");
    const [data, , options] = calls[0]!.params as [string, unknown[], Record<string, string>];
    expect(data).toBe("BASE64");
    expect(options["pause-metadata"]).toBe("true");
  });

  it("mode=metalink_data returns the first GID from addMetalink", async () => {
    const { client: c } = client(() => ["GID-A", "GID-B"]);
    const gid = await dispatchDownload(
      c,
      { ...baseItem, mode: "metalink_data", metalink_data: "BASE64" },
      { capBytesPerSec: 0, prefs },
    );
    expect(gid).toBe("GID-A");
  });

  it("desired_state=paused sets pause:true", async () => {
    const { client: c, calls } = client(() => "GID");
    await dispatchDownload(
      c,
      { ...baseItem, desired_state: "paused" },
      { capBytesPerSec: 0, prefs },
    );
    const [, options] = calls[0]!.params as [string[], Record<string, string>];
    expect(options.pause).toBe("true");
  });

  it("selected_files becomes a comma-joined select-file", async () => {
    const { client: c, calls } = client(() => "GID");
    await dispatchDownload(
      c,
      { ...baseItem, selected_files: [1, 3, 5] },
      { capBytesPerSec: 0, prefs },
    );
    const [, options] = calls[0]!.params as [string[], Record<string, string>];
    expect(options["select-file"]).toBe("1,3,5");
  });

  it("output with a directory component is NOT passed as `out`", async () => {
    const { client: c, calls } = client(() => "GID");
    await dispatchDownload(
      c,
      { ...baseItem, output: "/abs/path/file.iso" },
      { capBytesPerSec: 0, prefs },
    );
    const [, options] = calls[0]!.params as [string[], Record<string, string>];
    expect(options.out).toBeUndefined();
  });

  it("torrent_data mode requires data", async () => {
    const { client: c } = client(() => "GID");
    await expect(
      dispatchDownload(c, { ...baseItem, mode: "torrent_data" }, { capBytesPerSec: 0, prefs }),
    ).rejects.toThrow(/torrent_data/);
  });

  it("metalink_data mode rejects empty GID list", async () => {
    const { client: c } = client(() => []);
    await expect(
      dispatchDownload(
        c,
        { ...baseItem, mode: "metalink_data", metalink_data: "B" },
        { capBytesPerSec: 0, prefs },
      ),
    ).rejects.toThrow(/no GIDs/);
  });
});
