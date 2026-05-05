import { describe, expect, it } from "vitest";
import { planAutoCleanup, type QueueItem } from "./archivable.js";

const NOW = 1_700_000_000; // fixed epoch seconds
const hoursAgo = (h: number) => new Date((NOW - h * 3600) * 1000).toISOString();

describe("planAutoCleanup", () => {
  it("archives stale terminals, keeps fresh ones", () => {
    const stale: QueueItem = { status: "complete", completed_at: hoursAgo(300) };
    const fresh: QueueItem = { status: "complete", completed_at: hoursAgo(1) };
    const active: QueueItem = { status: "active" };
    const { keep, archive } = planAutoCleanup([stale, fresh, active], {
      maxDoneAgeDays: 7,
      now: NOW,
    });
    expect(archive).toEqual([stale]);
    expect(keep).toEqual([fresh, active]);
  });

  it("respects archiveNonComplete=false", () => {
    const errOld: QueueItem = { status: "error", error_at: hoursAgo(500) };
    const { keep, archive } = planAutoCleanup([errOld], {
      maxDoneAgeDays: 7,
      archiveNonComplete: false,
      now: NOW,
    });
    expect(archive).toEqual([]);
    expect(keep).toEqual([errOld]);
  });

  it("enforces maxDoneCount even on fresh complete items", () => {
    const items: QueueItem[] = Array.from({ length: 5 }, (_, i) => ({
      status: "complete",
      completed_at: hoursAgo(1),
      id: `c${i}`,
    }));
    const { keep, archive } = planAutoCleanup(items, {
      maxDoneAgeDays: 7,
      maxDoneCount: 2,
      now: NOW,
    });
    expect(archive).toHaveLength(3);
    expect(keep).toHaveLength(2);
    // The first 3 complete items get archived (FIFO)
    expect(archive.map((i) => i.id)).toEqual(["c0", "c1", "c2"]);
  });
});
