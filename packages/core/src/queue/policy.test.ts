import { describe, expect, it } from "vitest";
import { allowedActions, detectDownloadMode, summarizeQueue } from "./policy.js";
import type { QueueItemRecord } from "./types.js";

describe("allowedActions", () => {
  it("returns a fresh array per call", () => {
    const a = allowedActions("queued");
    a.push("hacked");
    expect(allowedActions("queued")).toEqual(["pause", "remove"]);
  });

  it.each([
    ["discovering", []],
    ["queued", ["pause", "remove"]],
    ["waiting", ["pause", "remove"]],
    ["active", ["pause", "remove"]],
    ["paused", ["resume", "remove"]],
    ["complete", ["remove"]],
    ["error", ["retry", "remove"]],
    ["removed", ["retry", "remove"]],
    ["stopped", []],
    ["unknown", []],
  ])("status=%s -> %j", (status, expected) => {
    expect(allowedActions(status)).toEqual(expected);
  });
});

describe("detectDownloadMode", () => {
  it("torrentData wins over everything", () => {
    expect(
      detectDownloadMode({ url: "http://x/y.torrent", torrentData: "abc" }),
    ).toBe("torrent_data");
  });
  it("metalinkData wins when no torrentData", () => {
    expect(detectDownloadMode({ url: "http://x", metalinkData: "abc" })).toBe(
      "metalink_data",
    );
  });
  it("mirrors with >1 entries -> mirror", () => {
    expect(
      detectDownloadMode({ url: "http://x", mirrors: ["http://x", "http://y"] }),
    ).toBe("mirror");
  });
  it("single-element mirrors does NOT trigger mirror", () => {
    expect(detectDownloadMode({ url: "http://x", mirrors: ["http://x"] })).toBe(
      "http",
    );
  });
  it("classifies by URL suffix / scheme", () => {
    expect(detectDownloadMode({ url: "magnet:?xt=urn:btih:abc" })).toBe("magnet");
    expect(detectDownloadMode({ url: "http://host/file.torrent" })).toBe("torrent");
    expect(detectDownloadMode({ url: "http://host/file.metalink" })).toBe("metalink");
    expect(detectDownloadMode({ url: "http://host/file.meta4" })).toBe("metalink");
    expect(detectDownloadMode({ url: "http://host/file.iso" })).toBe("http");
  });
  it("strips trailing query/fragment chars before suffix match", () => {
    expect(detectDownloadMode({ url: "http://host/x.torrent?" })).toBe("torrent");
    expect(detectDownloadMode({ url: "HTTP://Host/X.METALINK#" })).toBe("metalink");
  });
});

describe("summarizeQueue", () => {
  it("returns total + zero-padded status counts", () => {
    const summary = summarizeQueue([]);
    expect(summary.total).toBe(0);
    expect(summary.queued).toBe(0);
    expect(summary.active).toBe(0);
  });

  it("counts each status independently", () => {
    const items: QueueItemRecord[] = [
      { id: "1", url: "u", status: "active" },
      { id: "2", url: "u", status: "active" },
      { id: "3", url: "u", status: "complete" },
      { id: "4", url: "u", status: "queued" },
    ];
    const s = summarizeQueue(items);
    expect(s.total).toBe(4);
    expect(s.active).toBe(2);
    expect(s.complete).toBe(1);
    expect(s.queued).toBe(1);
    expect(s.paused).toBe(0);
  });
});
