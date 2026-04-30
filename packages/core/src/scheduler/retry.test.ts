import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ActionLog } from "../storage/action-log.js";
import { ArchiveStore, QueueStore } from "../storage/queue.js";
import { DeclarationStore } from "../storage/declaration.js";
import { SessionService } from "../storage/sessions.js";
import { StateStore } from "../storage/state.js";
import { StorageLock } from "../storage/lock.js";
import { storageLockPath } from "../storage/paths.js";
import { QueueOps } from "../queue/ops.js";
import { isRetryReady, runRetryPass } from "./retry.js";

let dir: string;
let queue: QueueStore;
let declaration: DeclarationStore;
let actions: ActionLog;
let queueOps: QueueOps;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-retry-"));
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  declaration = new DeclarationStore(lock, env);
  queueOps = new QueueOps(queue, sessions, declaration, actions);
});

afterEach(() => rmSync(dir, { recursive: true, force: true }));

const seedErroredItem = async (overrides: Record<string, unknown> = {}): Promise<string> => {
  const { item } = await queueOps.add({ url: "http://h/x" });
  const items = await queue.load();
  const rec = items[0]! as Record<string, unknown>;
  rec.status = "error";
  rec.gid = "OLD-GID";
  rec.error_code = "1";
  rec.error_message = "boom";
  rec.error_at = new Date().toISOString();
  Object.assign(rec, overrides);
  await queue.save(items);
  return item.id;
};

describe("runRetryPass", () => {
  it("reschedules an errored item back to queued and bumps retry_count", async () => {
    const id = await seedErroredItem();
    const r = await runRetryPass(
      { queueStore: queue, declarationStore: declaration, actionLog: actions },
      1_700_000_000_000,
    );
    expect(r.rescheduled).toHaveLength(1);
    expect(r.rescheduled[0]!.retry_count).toBe(1);
    const items = await queue.load();
    expect(items[0]!.status).toBe("queued");
    expect(items[0]!.gid).toBeNull();
    expect(items[0]!.error_code).toBeNull();
    const rec = items[0]! as Record<string, unknown>;
    expect(rec.retry_count).toBe(1);
    expect(typeof rec.retry_at).toBe("string");
    // Default backoff is 30s, retry_count=1 -> 30s in the future.
    expect(Date.parse(rec.retry_at as string)).toBe(1_700_000_000_000 + 30_000);
    // Sanity: id round-trip
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("respects max_retries and emits 'retry_exhausted' once", async () => {
    await seedErroredItem({ retry_count: 3 }); // default max_retries is 3
    const r1 = await runRetryPass({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
    });
    const r2 = await runRetryPass({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
    });
    expect(r1.exhausted).toHaveLength(1);
    expect(r2.exhausted).toHaveLength(1);
    const log = await actions.load();
    const exhaustedEvents = log.filter((e) => e.action === "retry_exhausted");
    expect(exhaustedEvents).toHaveLength(1); // recorded once thanks to retry_exhausted_at stamp
  });

  it("backs off proportionally to retry_count (30 * count seconds)", async () => {
    await seedErroredItem({ retry_count: 2 });
    const r = await runRetryPass(
      { queueStore: queue, declarationStore: declaration, actionLog: actions },
      1_700_000_000_000,
    );
    // After this pass retry_count=3, delay = 30 * 3 = 90 seconds.
    expect(Date.parse(r.rescheduled[0]!.retry_at)).toBe(1_700_000_000_000 + 90_000);
  });

  it("max_retries=0 disables auto-retry entirely", async () => {
    const decl = await declaration.load();
    decl.uic.preferences.find((p) => p.name === "max_retries")!.value = 0;
    await declaration.save(decl);
    await seedErroredItem();
    const r = await runRetryPass({
      queueStore: queue,
      declarationStore: declaration,
      actionLog: actions,
    });
    expect(r).toEqual({ rescheduled: [], exhausted: [] });
    const items = await queue.load();
    expect(items[0]!.status).toBe("error"); // unchanged
  });
});

describe("isRetryReady", () => {
  it("true when retry_at is missing or unparseable", () => {
    expect(isRetryReady({ id: "x", url: "u" })).toBe(true);
    expect(isRetryReady({ id: "x", url: "u", retry_at: "garbage" } as never)).toBe(true);
  });
  it("false while retry_at is in the future, true once past", () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    expect(isRetryReady({ id: "x", url: "u", retry_at: future } as never)).toBe(false);
    const past = new Date(Date.now() - 60_000).toISOString();
    expect(isRetryReady({ id: "x", url: "u", retry_at: past } as never)).toBe(true);
  });
});
