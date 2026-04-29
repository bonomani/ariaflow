import { describe, expect, it } from "vitest";
import {
  activeItemUrl,
  comparePreference,
  mergeActiveStatus,
  mergeQueueRows,
  normalizeQueueRow,
  queueItemPreference,
} from "./merge.js";
import { planCleanup } from "./cleanup.js";
import { queueItemForActiveInfo } from "./match.js";
import type { QueueItemRecord } from "../queue/types.js";

const item = (props: Partial<QueueItemRecord> = {}): QueueItemRecord => ({
  id: "i",
  url: "http://x",
  ...props,
});

describe("activeItemUrl", () => {
  it("walks files[0].uris[*].uri", () => {
    expect(
      activeItemUrl({ files: [{ uris: [{ uri: "http://h/a" }, { uri: "http://h/b" }] }] }),
    ).toBe("http://h/a");
  });
  it("falls back to files[0].path", () => {
    expect(activeItemUrl({ files: [{ path: "/dl/x" }] })).toBe("/dl/x");
  });
  it("returns null on missing/empty", () => {
    expect(activeItemUrl({})).toBeNull();
    expect(activeItemUrl({ files: [] })).toBeNull();
    expect(activeItemUrl({ files: [{}] })).toBeNull();
  });
});

describe("mergeActiveStatus", () => {
  it.each([
    ["active", "active"],
    ["paused", "paused"],
    ["waiting", "waiting"],
    ["complete", "complete"],
    ["error", "error"],
    [null, "active"],
    ["weird", "weird"],
  ])("%s -> %s", (input, expected) => {
    expect(mergeActiveStatus(input)).toBe(expected);
  });
});

describe("queueItemPreference / comparePreference", () => {
  it("ranks active above queued and queued above complete", () => {
    expect(comparePreference(item({ status: "active" }), item({ status: "queued" }))).toBe(1);
    expect(comparePreference(item({ status: "queued" }), item({ status: "complete" }))).toBe(1);
  });
  it("breaks ties by completed_length", () => {
    expect(
      comparePreference(
        item({ status: "active", completed_length: 100 }),
        item({ status: "active", completed_length: 50 }),
      ),
    ).toBe(1);
  });
  it("rewards rows that have a gid", () => {
    expect(
      comparePreference(
        item({ status: "queued", completed_length: 0, gid: "G" }),
        item({ status: "queued", completed_length: 0 }),
      ),
    ).toBe(1);
  });
  it("preference tuple shape is stable", () => {
    expect(queueItemPreference(item({ status: "active", gid: "G", completed_length: 5 }))).toEqual(
      [3, 5, 1, 0],
    );
  });
});

describe("mergeQueueRows", () => {
  it("fills empty string fields from the candidate", () => {
    const p = item({ url: "http://x", status: "queued" });
    const c = item({ url: "http://x", status: "queued", output: "f.iso", error_code: "1" });
    expect(mergeQueueRows(p, c)).toBe(true);
    expect(p.output).toBe("f.iso");
    expect(p.error_code).toBe("1");
  });

  it("does NOT overwrite populated fields", () => {
    const p = item({ output: "keep" });
    const c = item({ output: "drop" });
    expect(mergeQueueRows(p, c)).toBe(false);
    expect(p.output).toBe("keep");
  });

  it("takes the larger numeric value (download_speed/completed_length/total_length)", () => {
    const p = item({ completed_length: 10, total_length: 100 });
    const c = item({ completed_length: 50, total_length: 80 });
    mergeQueueRows(p, c);
    expect(p.completed_length).toBe(50);
    expect(p.total_length).toBe(100);
  });

  it("skips recovery_session_id once primary is terminal", () => {
    const p = item({ status: "complete" });
    const c = item({ recovery_session_id: "S", recovered_at: "T" });
    mergeQueueRows(p, c);
    expect((p as Record<string, unknown>).recovery_session_id).toBeUndefined();
  });
});

describe("normalizeQueueRow", () => {
  it("paused/active mismatch -> sets live_status=paused", () => {
    const it = item({ status: "paused", live_status: "active" });
    expect(normalizeQueueRow(it)).toBe(true);
    expect(it.live_status).toBe("paused");
  });
  it("status=error sets live_status=error", () => {
    const it = item({ status: "error" });
    expect(normalizeQueueRow(it)).toBe(true);
    expect(it.live_status).toBe("error");
  });
  it("status=complete strips live_status and recovery flags", () => {
    const it = item({
      status: "complete",
      live_status: "active",
      recovered: true,
      recovered_at: "T",
      recovery_session_id: "S",
    } as unknown as QueueItemRecord);
    expect(normalizeQueueRow(it)).toBe(true);
    expect(it.live_status).toBeUndefined();
    expect((it as Record<string, unknown>).recovered).toBeUndefined();
  });
});

describe("planCleanup", () => {
  it("dedupes by gid, keeping the preferred row and merging the other", () => {
    const a = item({ id: "1", url: "http://a", status: "queued", gid: "G" });
    const b = item({
      id: "2",
      url: "http://a",
      status: "active",
      gid: "G",
      completed_length: 50,
    });
    const out = planCleanup([a, b]);
    expect(out.removed).toBe(1);
    expect(out.changed).toBe(true);
    expect(out.items).toHaveLength(1);
    expect(out.items[0]!.id).toBe("2");
    expect(out.items[0]!.completed_length).toBe(50);
  });

  it("dedupes by url when gids differ", () => {
    const a = item({ id: "1", url: "http://x", status: "queued" });
    const b = item({ id: "2", url: "http://x", status: "queued" });
    expect(planCleanup([a, b]).items).toHaveLength(1);
  });

  it("counts normalized rows separately from removed rows", () => {
    const x = item({ id: "1", url: "http://x", status: "complete", live_status: "active" });
    const out = planCleanup([x]);
    expect(out.normalized).toBe(1);
    expect(out.removed).toBe(0);
    expect(out.changed).toBe(true);
  });
});

describe("queueItemForActiveInfo", () => {
  it("matches by gid first", () => {
    const items = [item({ id: "a", gid: "G1" }), item({ id: "b", gid: "G2" })];
    expect(queueItemForActiveInfo({ gid: "G2" }, items)!.id).toBe("b");
  });

  it("matches by exact url when gid is missing", () => {
    const items = [item({ id: "a", url: "http://h/x.iso" })];
    expect(
      queueItemForActiveInfo(
        { files: [{ uris: [{ uri: "http://h/x.iso" }] }] },
        items,
      )!.id,
    ).toBe("a");
  });

  it("matches by url tail across hosts", () => {
    const items = [item({ id: "a", url: "http://h1.example/foo/x.iso" })];
    const m = queueItemForActiveInfo(
      { files: [{ uris: [{ uri: "http://h2.other/x.iso?token=1" }] }] },
      items,
    );
    expect(m?.id).toBe("a");
  });

  it("scopes second-pass url matching by session_id", () => {
    // Pass-1 url matches 'a' (terminal=complete is allowed in pass 1, since
    // pass 1 walks all items). Verify that when pass-1 doesn't find a match
    // because the terminal row's url differs, pass-2 narrows by session and
    // picks the in-session row.
    const items = [
      item({ id: "a", url: "u-old", status: "complete", session_id: "S1" }),
      item({ id: "b", url: "u", status: "queued", session_id: "S2" }),
    ];
    const m = queueItemForActiveInfo({ gid: "Z", files: [{ path: "u" }] }, items, "S2");
    expect(m?.id).toBe("b");
  });

  it("returns null when nothing matches", () => {
    expect(queueItemForActiveInfo({ gid: "X" }, [])).toBeNull();
  });
});
