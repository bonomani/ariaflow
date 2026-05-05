import { describe, expect, it } from "vitest";
import { buildPrivateTorrent } from "./build.js";

describe("buildPrivateTorrent", () => {
  it("rejects empty files", () => {
    expect(() =>
      buildPrivateTorrent({
        name: "x",
        fileBytes: new Uint8Array(0),
        trackerUrl: "http://t/",
      }),
    ).toThrow(/empty/);
  });

  it("produces deterministic infohash for the same input", () => {
    const bytes = new Uint8Array(1024 * 300).map((_, i) => i & 0xff);
    const a = buildPrivateTorrent({ name: "f.bin", fileBytes: bytes, trackerUrl: "http://t/" });
    const b = buildPrivateTorrent({ name: "f.bin", fileBytes: bytes, trackerUrl: "http://t/" });
    expect(a.infohash).toBe(b.infohash);
    expect(a.infohash).toMatch(/^[0-9a-f]{40}$/);
    expect(a.fileSize).toBe(bytes.length);
    expect(a.pieceCount).toBeGreaterThan(0);
  });

  it("infohash differs when name or content changes", () => {
    const bytes = new Uint8Array([1, 2, 3, 4, 5]);
    const a = buildPrivateTorrent({ name: "a", fileBytes: bytes, trackerUrl: "http://t/" });
    const b = buildPrivateTorrent({ name: "b", fileBytes: bytes, trackerUrl: "http://t/" });
    const c = buildPrivateTorrent({
      name: "a",
      fileBytes: new Uint8Array([1, 2, 3, 4, 6]),
      trackerUrl: "http://t/",
    });
    expect(a.infohash).not.toBe(b.infohash);
    expect(a.infohash).not.toBe(c.infohash);
  });

});
