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
import { runSchedulerLoop } from "./loop.js";

let dir: string;
let queue: QueueStore;
let state: StateStore;
let actions: ActionLog;
let declaration: DeclarationStore;
let queueOps: QueueOps;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-loop-"));
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  state = new StateStore(lock, env);
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

const stagedClient = (
  ticks: Array<(req: { method: string; params: unknown[] }) => unknown>,
): Aria2Client => {
  let i = 0;
  const fetchImpl = async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
    const handler = ticks[Math.min(i, ticks.length - 1)]!;
    const result = handler(body);
    // Advance to the next stage on each tellActive (one per loop iter).
    if (body.method === "aria2.tellActive") i += 1;
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  return new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
};

describe("runSchedulerLoop", () => {
  it("dispatches a queued item, polls it complete, then drains", async () => {
    await queueOps.add({ url: "http://h/x" });
    const aria2 = stagedClient([
      // iter 1: addUri returns gid; tellActive sees it active.
      ({ method }) => {
        if (method === "aria2.addUri") return "GID-1";
        if (method === "aria2.tellActive")
          return [
            { gid: "GID-1", status: "active", totalLength: "10", completedLength: "5" },
          ];
        return "OK";
      },
      // iter 2: tellActive sees it complete.
      ({ method }) => {
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return { gid: "GID-1", status: "complete", totalLength: "10", completedLength: "10" };
        return "OK";
      },
    ]);

    const r = await runSchedulerLoop(
      {
        queueStore: queue,
        stateStore: state,
        declarationStore: declaration,
        actionLog: actions,
        aria2,
      },
      { intervalMs: 1, maxIterations: 5 },
    );
    expect(r.reason).toBe("drained");
    const items = await queue.load();
    expect(items[0]!.status).toBe("complete");
    const finalState = await state.load();
    expect(finalState.running).toBe(false);
  });

  it("skips dispatch but still polls when state.paused is true", async () => {
    await queueOps.add({ url: "http://h/y" });
    await state.update((s) => {
      s.paused = true;
    });
    let addCalls = 0;
    const aria2 = stagedClient([
      ({ method }) => {
        if (method === "aria2.addUri") {
          addCalls += 1;
          return "SHOULD-NOT-HAPPEN";
        }
        return method === "aria2.tellActive" ? [] : "OK";
      },
    ]);
    await runSchedulerLoop(
      {
        queueStore: queue,
        stateStore: state,
        declarationStore: declaration,
        actionLog: actions,
        aria2,
      },
      { intervalMs: 1, maxIterations: 1 },
    );
    expect(addCalls).toBe(0);
    const items = await queue.load();
    expect(items[0]!.status).toBe("queued"); // never moved
  });

  it("respects maxIterations when there's still in-flight work", async () => {
    await queueOps.add({ url: "http://h/z" });
    const aria2 = stagedClient([
      ({ method }) => {
        if (method === "aria2.addUri") return "GID-Z";
        if (method === "aria2.tellActive")
          return [
            { gid: "GID-Z", status: "active", totalLength: "100", completedLength: "10" },
          ];
        return "OK";
      },
    ]);
    const r = await runSchedulerLoop(
      {
        queueStore: queue,
        stateStore: state,
        declarationStore: declaration,
        actionLog: actions,
        aria2,
      },
      { intervalMs: 1, maxIterations: 2 },
    );
    expect(r.reason).toBe("max_iterations");
    expect(r.iterations).toBe(2);
    expect((await state.load()).running).toBe(false);
  });

  it("runs preLoop once before the first iteration and uses its returned cap", async () => {
    await queueOps.add({ url: "http://h/p" });
    let preLoopCalls = 0;
    let observedCap: number | undefined;
    const aria2 = stagedClient([
      ({ method, params }) => {
        if (method === "aria2.addUri") {
          const optsArg = (params[1] ?? {}) as Record<string, string>;
          observedCap = Number(optsArg["max-download-limit"]);
          return "GID-P";
        }
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return { gid: "GID-P", status: "complete", totalLength: "1", completedLength: "1" };
        return "OK";
      },
    ]);
    await runSchedulerLoop(
      {
        queueStore: queue,
        stateStore: state,
        declarationStore: declaration,
        actionLog: actions,
        aria2,
      },
      {
        intervalMs: 1,
        maxIterations: 5,
        preLoop: async () => {
          preLoopCalls += 1;
          return { capBytesPerSec: 250_000 };
        },
      },
    );
    expect(preLoopCalls).toBe(1);
    expect(observedCap).toBe(250_000);
  });

  it("logs scheduler_pre on preLoop error and falls back to opts.capBytesPerSec", async () => {
    await queueOps.add({ url: "http://h/q2" });
    const aria2 = stagedClient([
      ({ method }) => {
        if (method === "aria2.addUri") return "GID-Q2";
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return { gid: "GID-Q2", status: "complete", totalLength: "1", completedLength: "1" };
        return "OK";
      },
    ]);
    await runSchedulerLoop(
      {
        queueStore: queue,
        stateStore: state,
        declarationStore: declaration,
        actionLog: actions,
        aria2,
      },
      {
        intervalMs: 1,
        maxIterations: 3,
        capBytesPerSec: 100_000,
        preLoop: async () => {
          throw new Error("boom");
        },
      },
    );
    const log = await actions.load();
    const pre = log.find((e) => e.action === "scheduler_pre");
    expect(pre).toBeDefined();
    expect(pre!.outcome).toBe("failed");
  });

  it("calls aria2.pauseAll on shutdown to honor ASM CR-3", async () => {
    await queueOps.add({ url: "http://h/cr3" });
    const seen: string[] = [];
    const aria2 = stagedClient([
      ({ method }) => {
        seen.push(method);
        if (method === "aria2.addUri") return "GID-CR3";
        if (method === "aria2.tellActive") return [];
        if (method === "aria2.tellStatus")
          return { gid: "GID-CR3", status: "complete", totalLength: "1", completedLength: "1" };
        return "OK";
      },
    ]);
    await runSchedulerLoop(
      {
        queueStore: queue,
        stateStore: state,
        declarationStore: declaration,
        actionLog: actions,
        aria2,
      },
      { intervalMs: 1, maxIterations: 5 },
    );
    expect(seen).toContain("aria2.pauseAll");
  });

  it("aborts cleanly via AbortController and records 'scheduler_stopped'", async () => {
    await queueOps.add({ url: "http://h/q" });
    const aria2 = stagedClient([
      ({ method }) => {
        if (method === "aria2.addUri") return "GID-Q";
        if (method === "aria2.tellActive")
          return [
            { gid: "GID-Q", status: "active", totalLength: "1000", completedLength: "1" },
          ];
        return "OK";
      },
    ]);
    const ctrl = new AbortController();
    const promise = runSchedulerLoop(
      {
        queueStore: queue,
        stateStore: state,
        declarationStore: declaration,
        actionLog: actions,
        aria2,
      },
      {
        intervalMs: 1,
        signal: ctrl.signal,
        // Abort after the first iteration.
        onIteration: () => ctrl.abort(),
      },
    );
    const r = await promise;
    expect(r.reason).toBe("aborted");
    const log = await actions.load();
    expect(log.some((e) => e.action === "scheduler_stopped")).toBe(true);
  });
});
