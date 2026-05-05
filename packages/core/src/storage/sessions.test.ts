import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StorageLock } from "./lock.js";
import { storageLockPath } from "./paths.js";
import { StateStore } from "./state.js";
import { ArchiveStore, QueueStore } from "./queue.js";
import { ActionLog } from "./action-log.js";
import { SessionService } from "./sessions.js";

let dir: string;
let env: NodeJS.ProcessEnv;
let lock: StorageLock;
let state: StateStore;
let queue: QueueStore;
let archive: ArchiveStore;
let actions: ActionLog;
let sessions: SessionService;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-sess-"));
  env = { ARIAFLOW_DIR: dir };
  lock = new StorageLock(storageLockPath(env));
  state = new StateStore(lock, env);
  queue = new QueueStore(lock, env);
  archive = new ArchiveStore(lock, env);
  actions = new ActionLog(lock, state, env);
  sessions = new SessionService(lock, state, queue, archive, env, () =>
    new Date(0).toISOString(),
  );
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("ActionLog", () => {
  it("appends timestamped entries and reads them back", async () => {
    await actions.record({ action: "test", target: "queue", outcome: "changed" });
    await actions.record({ action: "test2", target: "queue", outcome: "changed" });
    const entries = await actions.load();
    expect(entries).toHaveLength(2);
    expect(entries[0]!.action).toBe("test");
    expect(entries[1]!.action).toBe("test2");
    expect(typeof entries[0]!.timestamp).toBe("string");
  });

  it("attaches session_id when one is open", async () => {
    await sessions.ensure();
    await actions.record({ action: "x", target: "y", outcome: "changed" });
    const entries = await actions.load();
    expect(typeof entries[0]!.session_id).toBe("string");
  });
});

describe("SessionService", () => {
  it("ensure() opens a session and is idempotent", async () => {
    const a = await sessions.ensure();
    const b = await sessions.ensure();
    expect(a.session_id).toBe(b.session_id);
    expect(a.session_started_at).toBe(b.session_started_at);
  });

  it("close() refuses while items are active or waiting (ASM CR-4)", async () => {
    await sessions.ensure();
    await queue.save([{ id: "a", url: "u", status: "active" }]);
    await expect(sessions.close()).rejects.toThrow(/ASM CR-4/);
  });

  it("close() succeeds when all items are terminal/queued/paused", async () => {
    await sessions.ensure();
    await queue.save([
      { id: "a", url: "u", status: "complete" },
      { id: "b", url: "u", status: "paused" },
    ]);
    const closed = await sessions.close("done");
    expect(closed.session_closed_at).not.toBeNull();
    expect(closed.session_closed_reason).toBe("done");
    const history = await sessions.loadHistory();
    expect(history).toHaveLength(1);
    expect(history[0]!.closed_reason).toBe("done");
  });

  it("startNew() pauses active items, closes, then opens a fresh session", async () => {
    const first = await sessions.ensure();
    await queue.save([
      { id: "a", url: "u", status: "active" },
      { id: "b", url: "u", status: "waiting" },
      { id: "c", url: "u", status: "complete" },
    ]);
    const second = await sessions.startNew("manual");
    expect(second.session_id).not.toBe(first.session_id);
    expect(second.session_closed_at).toBeNull();
    const items = await queue.load();
    expect(items.find((i) => i.id === "a")!.status).toBe("paused");
    expect(items.find((i) => i.id === "b")!.status).toBe("paused");
    expect(items.find((i) => i.id === "c")!.status).toBe("complete");
  });

  it("stats() summarizes the current session across queue + archive", async () => {
    const s = await sessions.ensure();
    const sid = s.session_id!;
    await queue.save([
      { id: "1", url: "u", status: "active", session_id: sid, completedLength: 100 },
      { id: "2", url: "u", status: "queued", session_id: sid },
      { id: "3", url: "u", status: "active", session_id: "other" },
    ]);
    await archive.save([
      { id: "4", url: "u", status: "complete", session_id: sid, completedLength: 50 },
    ]);
    const stats = await sessions.stats();
    expect(stats.items_total).toBe(3);
    expect(stats.items_active).toBe(2);
    expect(stats.items_archived).toBe(1);
    expect(stats.items_done).toBe(1);
    expect(stats.items_downloading).toBe(1);
    expect(stats.items_queued).toBe(1);
    expect(stats.bytes_completed).toBe(150);
  });

  it("publishes session_started / session_closed when a bus is attached", async () => {
    const { EventBus } = await import("../events/bus.js");
    const bus = new EventBus();
    sessions.setBus(bus);
    const events: string[] = [];
    bus.subscribe((event) => events.push(event));
    await sessions.ensure();
    await sessions.close("done");
    expect(events).toContain("session_started");
    expect(events).toContain("session_closed");
  });
});
