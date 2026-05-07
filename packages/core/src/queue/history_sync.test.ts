import { describe, expect, it } from "vitest";
import { markMissingByPath, updateOutputPath } from "./history_sync.js";
import type { QueueItemRecord } from "./types.js";

const item = (over: Partial<QueueItemRecord>): QueueItemRecord =>
  ({ id: over.id ?? "x", url: "http://h/x", ...over }) as QueueItemRecord;

describe("updateOutputPath (BG-56)", () => {
  it("rewrites every row whose output_path matches `from`", () => {
    const items = [
      item({ id: "a", output_path: "/dl/file.iso" }),
      item({ id: "b", output_path: "/dl/file.iso" }),
      item({ id: "c", output_path: "/dl/other" }),
    ];
    expect(updateOutputPath(items, "/dl/file.iso", "/dl/renamed.iso")).toBe(true);
    expect(items[0]!.output_path).toBe("/dl/renamed.iso");
    expect(items[1]!.output_path).toBe("/dl/renamed.iso");
    expect(items[2]!.output_path).toBe("/dl/other");
  });

  it("returns false and leaves rows untouched when no match", () => {
    const items = [item({ output_path: "/a" }), item({ output_path: undefined })];
    expect(updateOutputPath(items, "/missing", "/new")).toBe(false);
    expect(items[0]!.output_path).toBe("/a");
    expect(items[1]!.output_path).toBeUndefined();
  });
});

describe("markMissingByPath (BG-56)", () => {
  it("flags file_present_on_disk=false on rows whose output_path is in the set", () => {
    const items = [
      item({ id: "a", output_path: "/dl/gone.iso" }),
      item({ id: "b", output_path: "/dl/here.iso" }),
      item({ id: "c", output_path: undefined }),
    ];
    expect(markMissingByPath(items, new Set(["/dl/gone.iso"]))).toBe(true);
    expect(items[0]!.file_present_on_disk).toBe(false);
    expect(items[1]!.file_present_on_disk).toBeUndefined();
    expect(items[2]!.file_present_on_disk).toBeUndefined();
  });

  it("returns false on empty set", () => {
    const items = [item({ output_path: "/a" })];
    expect(markMissingByPath(items, new Set())).toBe(false);
    expect(items[0]!.file_present_on_disk).toBeUndefined();
  });
});
