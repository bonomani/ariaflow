import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Aria2Client } from "../aria2/client.js";
import { ActionLog } from "../storage/action-log.js";
import { ArchiveStore, QueueStore } from "../storage/queue.js";
import { DeclarationStore } from "../storage/declaration.js";
import { SessionService } from "../storage/sessions.js";
import { StateStore } from "../storage/state.js";
import { StorageLock } from "../storage/lock.js";
import { storageLockPath } from "../storage/paths.js";
import { QueueOps } from "../queue/ops.js";
import { runSchedulerTick } from "./tick.js";

let dir: string;
let env: NodeJS.ProcessEnv;
let queue: QueueStore;
let actions: ActionLog;
let declaration: DeclarationStore;
let queueOps: QueueOps;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-tick-"));
  env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  declaration = new DeclarationStore(lock, env);
  queueOps = new QueueOps(queue, sessions, declaration, actions);
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const fakeClient = (
  reply: (req: { method: string; params: unknown[] }) => unknown,
): { client: Aria2Client; calls: Array<{ method: string }> } => {
  const calls: Array<{ method: string }> = [];
  const fetchImpl = async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
    calls.push({ method: body.method });
    const result = reply(body);
    if (result instanceof Error) {
      return new Response(
        JSON.stringify({ jsonrpc: "2.0", id: "x", error: { code: 1, message: result.message } }),
      );
    }
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  return { client: new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch }), calls };
};

describe("runSchedulerTick", () => {
  it("dispatches the next queued item and persists gid + status=active", async () => {
    await queueOps.add({ url: "http://h/x.iso" });
    const { client, calls } = fakeClient(({ method }) =>
      method === "aria2.addUri" ? "GID-X" : "OK",
    );
    const result = await runSchedulerTick({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
      capBytesPerSec: 0,
    });
    expect(result.started).toHaveLength(1);
    expect(result.started[0]!.gid).toBe("GID-X");
    const items = await queue.load();
    expect(items[0]!.status).toBe("active");
    expect(items[0]!.gid).toBe("GID-X");
    expect(calls.some((c) => c.method === "aria2.addUri")).toBe(true);
  });

  it("respects max_simultaneous_downloads (default 1)", async () => {
    await queueOps.add({ url: "http://h/a" });
    await queueOps.add({ url: "http://h/b" });
    const { client } = fakeClient(({ method }) =>
      method === "aria2.addUri" ? "GID" : "OK",
    );
    const r = await runSchedulerTick({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
      capBytesPerSec: 0,
    });
    // The default declaration sets max_simultaneous_downloads=1.
    expect(r.started).toHaveLength(1);
    const items = await queue.load();
    expect(items.filter((i) => i.status === "active")).toHaveLength(1);
    expect(items.filter((i) => i.status === "queued")).toHaveLength(1);
  });

  it("returns saturated=true when active count already meets the cap", async () => {
    await queueOps.add({ url: "http://h/a" });
    // Mark the row as already-active (no gid yet) — pretend an earlier
    // tick started it elsewhere.
    const items = await queue.load();
    items[0]!.status = "active";
    items[0]!.gid = "EXISTING";
    await queue.save(items);
    const { client, calls } = fakeClient(() => "GID");
    const r = await runSchedulerTick({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
      capBytesPerSec: 0,
    });
    expect(r.saturated).toBe(true);
    expect(r.started).toEqual([]);
    expect(calls).toHaveLength(0);
  });

  it("records a 'start_failed' action when the RPC throws", async () => {
    await queueOps.add({ url: "http://h/x" });
    const { client } = fakeClient(({ method }) =>
      method === "aria2.addUri" ? new Error("aria2 unreachable") : "OK",
    );
    const r = await runSchedulerTick({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
      capBytesPerSec: 0,
    });
    expect(r.failed).toHaveLength(1);
    const log = await actions.load();
    expect(log.some((e) => e.action === "start_failed")).toBe(true);
    // The local row stays "queued" since we never wrote a gid.
    const items = await queue.load();
    expect(items[0]!.status).toBe("queued");
    expect(items[0]!.gid ?? null).toBeNull();
  });

  it("orders candidates by priority desc", async () => {
    await queueOps.add({ url: "http://h/low", priority: 1 });
    await queueOps.add({ url: "http://h/high", priority: 5 });
    // Bump the cap so we'd start both, but we only check ordering of the first.
    const decl = await declaration.load();
    decl.uic.preferences.find((p) => p.name === "max_simultaneous_downloads")!.value = 1;
    await declaration.save(decl);
    const dispatched: string[] = [];
    const fetchImpl = vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
      if (body.method === "aria2.addUri") {
        dispatched.push(((body.params[0] as string[]) ?? [""])[0]!);
      }
      return new Response(
        JSON.stringify({ jsonrpc: "2.0", id: "x", result: "GID" }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    const client = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
    await runSchedulerTick({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
      capBytesPerSec: 0,
    });
    expect(dispatched[0]).toBe("http://h/high");
  });

  it("BG-28(a): stamps state.active_gid / active_url on the dispatched item", async () => {
    await queueOps.add({ url: "http://h/foo.iso" });
    const lock = new StorageLock(storageLockPath(env));
    const state = new StateStore(lock, env);
    const { client } = fakeClient(({ method }) => (method === "aria2.addUri" ? "GID-A" : "OK"));
    await runSchedulerTick({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
      aria2: client,
      capBytesPerSec: 0,
      stateStore: state,
    });
    const s = await state.load();
    expect(s.active_gid).toBe("GID-A");
    expect(s.active_url).toBe("http://h/foo.iso");
  });
});
