import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ActionLog } from "../storage/action-log.js";
import { DeclarationStore } from "../storage/declaration.js";
import { StorageLock } from "../storage/lock.js";
import { storageLockPath } from "../storage/paths.js";
import { ArchiveStore, QueueStore } from "../storage/queue.js";
import { SessionService } from "../storage/sessions.js";
import { StateStore } from "../storage/state.js";
import { QueueOps } from "./ops.js";
import { findLiveItemByUrl } from "./lookup.js";

let dir: string;
let env: NodeJS.ProcessEnv;
let queue: QueueStore;
let ops: QueueOps;
let actions: ActionLog;
let sessions: SessionService;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-ops-"));
  env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  actions = new ActionLog(lock, state, env);
  sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  ops = new QueueOps(queue, sessions, declaration, actions);
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("QueueOps.add", () => {
  it("creates a queued item and stamps session_history when a session is open", async () => {
    const { item, duplicate } = await ops.add({ url: "http://x/y" });
    expect(duplicate).toBe(false);
    expect(item.status).toBe("queued");
    expect(item.mode).toBe("http");
    expect(item.session_id).toBeTruthy();
    expect(item.session_history).toEqual([
      { session_id: item.session_id, joined_at: item.created_at, reason: "created" },
    ]);
    const persisted = await queue.load();
    expect(persisted).toHaveLength(1);
  });

  it("dedupes against a live URL match", async () => {
    await ops.add({ url: "http://x/y" });
    const { item, duplicate } = await ops.add({ url: "http://x/y" });
    expect(duplicate).toBe(true);
    const all = await queue.load();
    expect(all).toHaveLength(1);
    expect(item.id).toBe(all[0]!.id);
  });

  it("does NOT dedupe against a terminal-status item", async () => {
    const first = await ops.add({ url: "http://x/y" });
    await ops.transitionStatus(first.item.id, "complete", "completed_at");
    const second = await ops.add({ url: "http://x/y" });
    expect(second.duplicate).toBe(false);
    expect(second.item.id).not.toBe(first.item.id);
  });

  it("uses post_action_rule from the declaration when none supplied", async () => {
    const { item } = await ops.add({ url: "http://x/y" });
    expect(item.post_action_rule).toBe("pending");
  });

  it("classifies torrent / magnet / metalink modes", async () => {
    const a = await ops.add({ url: "magnet:?xt=urn:btih:abc" });
    const b = await ops.add({ url: "http://h/x.torrent" });
    const c = await ops.add({ url: "http://h/y.metalink" });
    expect(a.item.mode).toBe("magnet");
    expect(b.item.mode).toBe("torrent");
    expect(c.item.mode).toBe("metalink");
  });

  it("records add actions in the log", async () => {
    await ops.add({ url: "http://x/y" });
    await ops.add({ url: "http://x/y" }); // duplicate
    const log = await actions.load();
    const adds = log.filter((e) => e.action === "add");
    expect(adds.map((e) => e.outcome)).toEqual(["changed", "unchanged"]);
  });
});

describe("QueueOps.transitionStatus / remove", () => {
  it("transitionStatus updates status and records the action", async () => {
    const { item } = await ops.add({ url: "http://x" });
    const next = await ops.transitionStatus(item.id, "paused", "paused_at");
    expect(next!.status).toBe("paused");
    expect(typeof next!.paused_at).toBe("string");
  });

  it("transitionStatus returns null for unknown ids", async () => {
    expect(await ops.transitionStatus("nope", "paused")).toBeNull();
  });

  it("remove() drops the record from queue.json", async () => {
    const { item } = await ops.add({ url: "http://x" });
    expect(await ops.remove(item.id)).toMatchObject({ id: item.id });
    expect(await queue.load()).toEqual([]);
  });
});

describe("lookup helpers", () => {
  it("findLiveItemByUrl returns null when only terminal copies exist", () => {
    const items = [{ id: "1", url: "u", status: "complete" }];
    expect(findLiveItemByUrl(items, "u")).toBeNull();
  });
});
