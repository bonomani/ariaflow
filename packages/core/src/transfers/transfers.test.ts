import { describe, expect, it } from "vitest";
import { dedupActiveTransferAction, maxSimultaneousDownloads } from "./helpers.js";
import { buildTransferSummary, rankActiveInfos } from "./progress.js";
import { defaultDeclaration } from "../contracts/declaration.js";
import type { Aria2Status } from "../aria2/methods.js";

describe("dedupActiveTransferAction / maxSimultaneousDownloads", () => {
  it("dedupActiveTransferAction default is 'remove'", () => {
    expect(dedupActiveTransferAction(defaultDeclaration())).toBe("remove");
  });

  it("dedupActiveTransferAction preserves only allowed values", () => {
    const decl = defaultDeclaration();
    const pref = decl.uic.preferences.find(
      (p) => p.name === "duplicate_active_transfer_action",
    )!;
    pref.value = "PAUSE  ";
    expect(dedupActiveTransferAction(decl)).toBe("pause");
    pref.value = "weird";
    expect(dedupActiveTransferAction(decl)).toBe("remove");
  });

  it("maxSimultaneousDownloads default is 1 (per declaration)", () => {
    expect(maxSimultaneousDownloads(defaultDeclaration())).toBe(1);
  });

  it("maxSimultaneousDownloads clamps negatives and rejects NaN", () => {
    const decl = defaultDeclaration();
    const pref = decl.uic.preferences.find((p) => p.name === "max_simultaneous_downloads")!;
    pref.value = -5;
    expect(maxSimultaneousDownloads(decl)).toBe(0);
    pref.value = "abc";
    expect(maxSimultaneousDownloads(decl)).toBe(0);
  });
});

describe("buildTransferSummary", () => {
  it("computes percent from total/completed lengths", () => {
    const info: Aria2Status = {
      gid: "G",
      status: "active",
      totalLength: "1000",
      completedLength: "250",
      downloadSpeed: "42",
    };
    expect(buildTransferSummary(info, "http://x")).toMatchObject({
      gid: "G",
      url: "http://x",
      status: "active",
      download_speed: "42",
      completed_length: "250",
      total_length: "1000",
      percent: 25,
    });
  });

  it("returns percent=0 when totalLength is missing/zero", () => {
    expect(buildTransferSummary({ gid: "G", status: "active" }, null).percent).toBe(0);
  });

  it("flags recovered=true when requested", () => {
    const out = buildTransferSummary({ gid: "G", status: "active" }, null, { recovered: true });
    expect(out.recovered).toBe(true);
  });
});

describe("rankActiveInfos", () => {
  it("ranks by completion percent, then completed bytes, then speed", () => {
    const a: Aria2Status = {
      gid: "a",
      status: "active",
      totalLength: "100",
      completedLength: "10",
      downloadSpeed: "1",
    }; // 10%
    const b: Aria2Status = {
      gid: "b",
      status: "active",
      totalLength: "100",
      completedLength: "60",
      downloadSpeed: "0",
    }; // 60%
    const c: Aria2Status = {
      gid: "c",
      status: "active",
      totalLength: "100",
      completedLength: "60",
      downloadSpeed: "999",
    }; // 60%, ties broken by speed
    const ranked = rankActiveInfos([a, b, c]);
    expect(ranked.map((i) => i.gid)).toEqual(["c", "b", "a"]);
  });

  it("does not mutate the input array", () => {
    const arr: Aria2Status[] = [
      { gid: "a", status: "active", totalLength: "1", completedLength: "0" },
    ];
    rankActiveInfos(arr);
    expect(arr.map((i) => i.gid)).toEqual(["a"]);
  });
});
