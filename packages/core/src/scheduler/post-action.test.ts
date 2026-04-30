import { mkdtempSync, rmSync, writeFileSync, existsSync } from "node:fs";
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
import { runPostAction } from "./post-action.js";

let dir: string;
let queue: QueueStore;
let declaration: DeclarationStore;
let actions: ActionLog;
let queueOps: QueueOps;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-post-"));
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

const stubAria2 = (
  reply: (req: { method: string; params: unknown[] }) => unknown,
): Aria2Client => {
  const fetchImpl = async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result: reply(body) }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  return new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
};

describe("runPostAction", () => {
  it("no-ops without distribute flag or tracker URL", async () => {
    const { item } = await queueOps.add({ url: "http://h/x.iso" });
    const r = await runPostAction(
      {
        queueStore: queue,
        declarationStore: declaration,
        actionLog: actions,
        aria2: stubAria2(() => "OK"),
      },
      item.id,
    );
    expect(r.distribute).toBeUndefined();
    expect(r.success).toBe(true);
  });

  it("returns 'not_found' when the item id is missing", async () => {
    const r = await runPostAction(
      {
        queueStore: queue,
        declarationStore: declaration,
        actionLog: actions,
        aria2: stubAria2(() => "OK"),
      },
      "00000000-0000-0000-0000-000000000000",
    );
    expect(r).toEqual({
      item_id: "00000000-0000-0000-0000-000000000000",
      success: false,
      reason: "not_found",
      detail: "queue item missing",
    });
  });

  it("auto-distributes a completed http download into a torrent + addTorrent", async () => {
    // Set the tracker URL so distribution is enabled.
    const decl = await declaration.load();
    decl.uic.preferences.find((p) => p.name === "internal_tracker_url")!.value =
      "http://tracker.local/announce";
    await declaration.save(decl);

    // Add a queued item with distribute=true.
    const downloadDir = join(dir, "downloads");
    const fs = await import("node:fs/promises");
    await fs.mkdir(downloadDir, { recursive: true });
    const fileName = "x.iso";
    writeFileSync(join(downloadDir, fileName), Buffer.from("CONTENTS"));

    const { item } = await queueOps.add({
      url: "http://h/x.iso",
      output: fileName,
      distribute: true,
    });

    const seenMethods: string[] = [];
    const aria2 = stubAria2(({ method }) => {
      seenMethods.push(method);
      if (method === "aria2.getGlobalOption") return { dir: downloadDir };
      if (method === "aria2.addTorrent") return "SEED-GID";
      return "OK";
    });

    const r = await runPostAction(
      { queueStore: queue, declarationStore: declaration, actionLog: actions, aria2 },
      item.id,
    );

    expect(r.distribute).toBeDefined();
    expect(r.distribute!.success).toBe(true);
    if (r.distribute!.success) {
      expect(r.distribute!.seed_gid).toBe("SEED-GID");
      expect(r.distribute!.infohash).toMatch(/^[0-9a-f]{40}$/);
      expect(existsSync(r.distribute!.torrent_path)).toBe(true);
    }
    expect(seenMethods).toContain("aria2.addTorrent");
    const items = await queue.load();
    const persisted = items[0]! as Record<string, unknown>;
    expect(persisted.distribute_status).toBe("seeding");
    expect(persisted.distribute_seed_gid).toBe("SEED-GID");
    const log = await actions.load();
    expect(log.some((e) => e.action === "distribute_started")).toBe(true);
  });

  it("reports a soft failure when the file isn't on disk", async () => {
    const decl = await declaration.load();
    decl.uic.preferences.find((p) => p.name === "internal_tracker_url")!.value =
      "http://tracker.local/announce";
    await declaration.save(decl);
    const { item } = await queueOps.add({
      url: "http://h/missing.iso",
      output: "missing.iso",
      distribute: true,
    });
    const aria2 = stubAria2(({ method }) =>
      method === "aria2.getGlobalOption" ? { dir: "/nope" } : "OK",
    );
    const r = await runPostAction(
      { queueStore: queue, declarationStore: declaration, actionLog: actions, aria2 },
      item.id,
    );
    expect(r.distribute).toEqual({
      success: false,
      reason: expect.stringMatching(/file not found/),
    });
  });
});
