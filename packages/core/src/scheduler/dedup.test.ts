import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Aria2Client } from "../aria2/client.js";
import { ActionLog } from "../storage/action-log.js";
import { DeclarationStore } from "../storage/declaration.js";
import { StateStore } from "../storage/state.js";
import { StorageLock } from "../storage/lock.js";
import { storageLockPath } from "../storage/paths.js";
import { deduplicateActiveTransfers } from "./dedup.js";

let dir: string;
let declaration: DeclarationStore;
let actions: ActionLog;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-dedup-"));
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  actions = new ActionLog(lock, state, env);
  declaration = new DeclarationStore(lock, env);
});

afterEach(() => rmSync(dir, { recursive: true, force: true }));

const stagedClient = (
  reply: (req: { method: string; params: unknown[] }) => unknown,
): { client: Aria2Client; calls: Array<{ method: string; params: unknown[] }> } => {
  const calls: Array<{ method: string; params: unknown[] }> = [];
  const fetchImpl = async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
    calls.push({ method: body.method, params: body.params });
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result: reply(body) }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  return { client: new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch }), calls };
};

describe("deduplicateActiveTransfers", () => {
  it("no-op when fewer than 2 active jobs", async () => {
    const { client } = stagedClient(({ method }) =>
      method === "aria2.tellActive"
        ? [{ gid: "ONLY", status: "active", files: [{ uris: [{ uri: "http://h/x" }] }] }]
        : "OK",
    );
    const r = await deduplicateActiveTransfers({
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
    });
    expect(r.changed).toBe(false);
    expect(r.kept).toEqual([]);
  });

  it("keeps the most-progressed duplicate and removes the rest by default", async () => {
    const active = [
      {
        gid: "BEHIND",
        status: "active",
        totalLength: "100",
        completedLength: "10",
        files: [{ uris: [{ uri: "http://h/x" }] }],
      },
      {
        gid: "AHEAD",
        status: "active",
        totalLength: "100",
        completedLength: "80",
        files: [{ uris: [{ uri: "http://h/x" }] }],
      },
    ];
    const { client, calls } = stagedClient(({ method }) =>
      method === "aria2.tellActive" ? active : "OK",
    );
    const r = await deduplicateActiveTransfers({
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
    });
    expect(r.changed).toBe(true);
    expect(r.action).toBe("remove");
    expect(r.kept).toEqual(["AHEAD"]);
    expect(r.paused).toEqual(["BEHIND"]);
    const removeCall = calls.find((c) => c.method === "aria2.remove");
    expect(removeCall?.params).toEqual(["BEHIND"]);
  });

  it("respects duplicate_active_transfer_action='pause'", async () => {
    const decl = await declaration.load();
    decl.uic.preferences.find(
      (p) => p.name === "duplicate_active_transfer_action",
    )!.value = "pause";
    await declaration.save(decl);
    const active = [
      { gid: "A", status: "active", totalLength: "100", completedLength: "5", files: [{ uris: [{ uri: "u" }] }] },
      { gid: "B", status: "active", totalLength: "100", completedLength: "70", files: [{ uris: [{ uri: "u" }] }] },
    ];
    const { client, calls } = stagedClient(({ method }) =>
      method === "aria2.tellActive" ? active : "OK",
    );
    const r = await deduplicateActiveTransfers({
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
    });
    expect(r.action).toBe("pause");
    const pauseCall = calls.find((c) => c.method === "aria2.pause");
    expect(pauseCall?.params).toEqual(["A"]);
    const removeCall = calls.find((c) => c.method === "aria2.remove");
    expect(removeCall).toBeUndefined();
  });

  it("respects 'ignore' policy — keepers reported, no RPC writes", async () => {
    const decl = await declaration.load();
    decl.uic.preferences.find(
      (p) => p.name === "duplicate_active_transfer_action",
    )!.value = "ignore";
    await declaration.save(decl);
    const active = [
      { gid: "A", status: "active", totalLength: "100", completedLength: "5", files: [{ uris: [{ uri: "u" }] }] },
      { gid: "B", status: "active", totalLength: "100", completedLength: "70", files: [{ uris: [{ uri: "u" }] }] },
    ];
    const { client, calls } = stagedClient(({ method }) =>
      method === "aria2.tellActive" ? active : "OK",
    );
    const r = await deduplicateActiveTransfers({
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
    });
    expect(r.changed).toBe(false);
    expect(r.action).toBe("ignore");
    expect(r.kept.sort()).toEqual(["A", "B"]);
    expect(calls.some((c) => c.method === "aria2.remove" || c.method === "aria2.pause")).toBe(false);
  });

  it("aria2 unreachable -> graceful no-op", async () => {
    const client = new Aria2Client({
      fetch: (async () => {
        throw new Error("boom");
      }) as unknown as typeof fetch,
    });
    const r = await deduplicateActiveTransfers({
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
    });
    expect(r).toEqual({ changed: false, kept: [], paused: [], action: "ignore" });
  });
});
