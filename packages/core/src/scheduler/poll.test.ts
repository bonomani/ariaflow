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
import { pollActiveItems } from "./poll.js";

let dir: string;
let queue: QueueStore;
let actions: ActionLog;
let queueOps: QueueOps;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-poll-"));
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  queueOps = new QueueOps(queue, sessions, declaration, actions);
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const client = (
  reply: (req: { method: string; params: unknown[] }) => unknown,
): Aria2Client => {
  const fetchImpl = async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
    const result = reply(body);
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  return new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
};

describe("pollActiveItems", () => {
  const seedActiveItem = async (gid: string) => {
    const { item } = await queueOps.add({ url: "http://h/x" });
    const items = await queue.load();
    items[0]!.gid = gid;
    items[0]!.status = "active";
    await queue.save(items);
    return item.id;
  };

  it("returns empty arrays when nothing has a gid yet", async () => {
    await queueOps.add({ url: "http://h/y" });
    const r = await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(() => []),
    });
    expect(r).toEqual({ active: [], completed: [], errored: [], updated: [] });
  });

  it("transitions an item to complete and stamps completed_at", async () => {
    const id = await seedActiveItem("GID-OK");
    const r = await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(({ method }) => {
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return {
            gid: "GID-OK",
            status: "complete",
            totalLength: "100",
            completedLength: "100",
          };
        return "OK";
      }),
    });
    expect(r.completed).toEqual([{ id, gid: "GID-OK" }]);
    const items = await queue.load();
    expect(items[0]!.status).toBe("complete");
    expect(typeof items[0]!.completed_at).toBe("string");
  });

  it("transitions to error and stamps error_code/message", async () => {
    const id = await seedActiveItem("GID-ERR");
    const r = await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(({ method }) => {
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return {
            gid: "GID-ERR",
            status: "error",
            errorCode: "1",
            errorMessage: "boom",
          };
        return "OK";
      }),
    });
    expect(r.errored).toEqual([
      { id, gid: "GID-ERR", error_code: "1", error_message: "boom" },
    ]);
    const items = await queue.load();
    expect(items[0]!.status).toBe("error");
    expect(items[0]!.error_code).toBe("1");
    expect(items[0]!.error_message).toBe("boom");
  });

  it("refreshes live progress fields without flipping status when active", async () => {
    const id = await seedActiveItem("GID-LIVE");
    const r = await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(({ method }) => {
        if (method === "aria2.tellActive")
          return [
            {
              gid: "GID-LIVE",
              status: "active",
              totalLength: "1000",
              completedLength: "250",
              downloadSpeed: "42",
            },
          ];
        return "OK";
      }),
    });
    expect(r.completed).toEqual([]);
    expect(r.errored).toEqual([]);
    expect(r.updated.length).toBeLessThanOrEqual(1);
    const items = await queue.load();
    expect(items[0]!.status).toBe("active"); // unchanged
    expect((items[0] as Record<string, unknown>).downloadSpeed).toBe("42");
    expect((items[0] as Record<string, unknown>).completedLength).toBe("250");
    expect(items[0]!.live_status).toBe("active");
    // sanity: id round-trip
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("BG-28(b): mirrors aria2 camelCase progress keys onto the row", async () => {
    await seedActiveItem("GID-CAM");
    await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(({ method }) => {
        if (method === "aria2.tellActive")
          return [
            {
              gid: "GID-CAM",
              status: "active",
              totalLength: "1000",
              completedLength: "300",
              downloadSpeed: "100",
              uploadSpeed: "5",
              connections: "8",
            },
          ];
        return "OK";
      }),
    });
    const items = await queue.load();
    const row = items[0] as Record<string, unknown>;
    expect(row.downloadSpeed).toBe("100");
    expect(row.uploadSpeed).toBe("5");
    expect(row.completedLength).toBe("300");
    expect(row.totalLength).toBe("1000");
    expect(row.connections).toBe("8");
  });

  it("BG-28(a): keeps state.active_gid pointed at the live active item then clears on terminal", async () => {
    const env = { ARIAFLOW_DIR: dir };
    const lock = new StorageLock(storageLockPath(env));
    const state = new StateStore(lock, env);
    await seedActiveItem("GID-A");
    // Active in aria2 → state should track it.
    await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      stateStore: state,
      aria2: client(({ method }) =>
        method === "aria2.tellActive"
          ? [{ gid: "GID-A", status: "active", totalLength: "10", completedLength: "1" }]
          : "OK",
      ),
    });
    let s = await state.load();
    expect(s.active_gid).toBe("GID-A");
    expect(s.active_url).toBe("http://h/x");
    // Now aria2 says complete → state clears.
    await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      stateStore: state,
      aria2: client(({ method }) => {
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return { gid: "GID-A", status: "complete", totalLength: "10", completedLength: "10" };
        return "OK";
      }),
    });
    s = await state.load();
    expect(s.active_gid).toBeNull();
    expect(s.active_url).toBeNull();
  });

  it("appends a 'transition' action per terminal switch", async () => {
    await seedActiveItem("GID-DONE");
    await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(({ method }) => {
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return { gid: "GID-DONE", status: "complete", totalLength: "1", completedLength: "1" };
        return "OK";
      }),
    });
    const log = await actions.load();
    expect(
      log.some(
        (e) => e.action === "transition" && e.reason === "status:complete",
      ),
    ).toBe(true);
  });

  it("BG-30 #1: persists waiting status when aria2 reports waiting", async () => {
    await seedActiveItem("GID-WAIT");
    await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(({ method }) =>
        method === "aria2.tellActive"
          ? [{ gid: "GID-WAIT", status: "waiting", totalLength: "10", completedLength: "0" }]
          : "OK",
      ),
    });
    const items = await queue.load();
    expect(items[0]!.status).toBe("waiting");
    expect(items[0]!.live_status).toBe("waiting");
  });

  it("BG-30 #2: emits canonical 'removed' (not legacy 'stopped') on aria2 removal", async () => {
    await seedActiveItem("GID-RM");
    await pollActiveItems({
      queueStore: queue,
      actionLog: actions,
      aria2: client(({ method }) => {
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return { gid: "GID-RM", status: "removed", totalLength: "1", completedLength: "0" };
        return "OK";
      }),
    });
    const items = await queue.load();
    expect(items[0]!.status).toBe("removed");
    expect(typeof items[0]!.removed_at).toBe("string");
  });
});
