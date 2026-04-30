import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Aria2Client } from "../aria2/client.js";
import { ActionLog } from "../storage/action-log.js";
import { ArchiveStore, QueueStore } from "../storage/queue.js";
import { DeclarationStore } from "../storage/declaration.js";
import { SessionService } from "../storage/sessions.js";
import { StateStore } from "../storage/state.js";
import { StorageLock } from "../storage/lock.js";
import { storageLockPath } from "../storage/paths.js";
import { QueueOps } from "../queue/ops.js";
import { reconcileLiveQueue } from "./reconcile.js";

let dir: string;
let queue: QueueStore;
let state: StateStore;
let actions: ActionLog;
let queueOps: QueueOps;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-rec-"));
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  state = new StateStore(lock, env);
  queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  queueOps = new QueueOps(queue, sessions, declaration, actions);
});

afterEach(() => rmSync(dir, { recursive: true, force: true }));

const stubAria2 = (active: unknown[]): Aria2Client =>
  new Aria2Client({
    fetch: (async () =>
      new Response(
        JSON.stringify({ jsonrpc: "2.0", id: "x", result: active }),
        { status: 200, headers: { "content-type": "application/json" } },
      )) as unknown as typeof fetch,
  });

const errorClient = (): Aria2Client =>
  new Aria2Client({
    fetch: (async () => {
      throw new Error("aria2 unreachable");
    }) as unknown as typeof fetch,
  });

describe("reconcileLiveQueue", () => {
  it("adopts an orphan aria2 GID into a fresh queue row", async () => {
    await state.update((s) => {
      s.session_id = "S1";
    });
    const aria2 = stubAria2([
      {
        gid: "ORPHAN-1",
        status: "active",
        files: [{ uris: [{ uri: "http://h/orphan.iso" }] }],
      },
    ]);
    const r = await reconcileLiveQueue({ queueStore: queue, stateStore: state, actionLog: actions, aria2 });
    expect(r.changed).toBe(true);
    expect(r.recovered).toBe(1);
    const items = await queue.load();
    expect(items).toHaveLength(1);
    expect(items[0]!.gid).toBe("ORPHAN-1");
    expect(items[0]!.url).toBe("http://h/orphan.iso");
    expect(items[0]!.status).toBe("active");
    expect(items[0]!.session_id).toBe("S1");
    expect((items[0] as Record<string, unknown>).recovered).toBe(true);
  });

  it("merges live status onto an existing matching row", async () => {
    await state.update((s) => {
      s.session_id = "S1";
    });
    const { item } = await queueOps.add({ url: "http://h/x.iso" });
    // Pretend the row already had an aria2 GID assigned.
    const items = await queue.load();
    items[0]!.gid = "GID-X";
    items[0]!.status = "queued";
    await queue.save(items);
    const aria2 = stubAria2([
      {
        gid: "GID-X",
        status: "active",
        files: [{ uris: [{ uri: "http://h/x.iso" }] }],
      },
    ]);
    const r = await reconcileLiveQueue({ queueStore: queue, stateStore: state, actionLog: actions, aria2 });
    expect(r.changed).toBe(true);
    const after = await queue.load();
    expect(after[0]!.id).toBe(item.id);
    expect(after[0]!.status).toBe("active");
    expect(after[0]!.live_status).toBe("active");
  });

  it("flags rows from a different session as recovered + bumps session_id", async () => {
    await state.update((s) => {
      s.session_id = "S2";
    });
    const { item } = await queueOps.add({ url: "http://h/y.iso" });
    const items = await queue.load();
    items[0]!.gid = "GID-Y";
    items[0]!.session_id = "S1"; // older session
    await queue.save(items);
    const aria2 = stubAria2([
      { gid: "GID-Y", status: "active", files: [{ uris: [{ uri: "http://h/y.iso" }] }] },
    ]);
    const r = await reconcileLiveQueue({ queueStore: queue, stateStore: state, actionLog: actions, aria2 });
    expect(r.recovered).toBe(1);
    const after = await queue.load();
    expect(after[0]!.id).toBe(item.id);
    expect(after[0]!.session_id).toBe("S2");
    expect((after[0] as Record<string, unknown>).recovered).toBe(true);
  });

  it("respects adoptMissing=false — no row created for orphan GIDs", async () => {
    const aria2 = stubAria2([
      { gid: "ORPHAN-2", status: "active", files: [{ uris: [{ uri: "http://h/o.iso" }] }] },
    ]);
    const r = await reconcileLiveQueue(
      { queueStore: queue, stateStore: state, actionLog: actions, aria2 },
      { adoptMissing: false },
    );
    expect(r.changed).toBe(false);
    expect(r.recovered).toBe(0);
    expect(await queue.load()).toEqual([]);
  });

  it("returns gracefully when aria2 is unreachable", async () => {
    const r = await reconcileLiveQueue({ queueStore: queue, stateStore: state, actionLog: actions, aria2: errorClient() });
    expect(r).toEqual({ changed: false, recovered: 0, active_count: 0, items: [] });
  });
});
