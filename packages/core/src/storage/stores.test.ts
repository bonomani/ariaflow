import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StorageLock } from "./lock.js";
import { storageLockPath } from "./paths.js";
import { DeclarationStore } from "./declaration.js";
import { StateStore } from "./state.js";
import { ArchiveStore, QueueStore } from "./queue.js";

let dir: string;
let env: NodeJS.ProcessEnv;
let lock: StorageLock;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-stores-"));
  env = { ARIAFLOW_DIR: dir };
  lock = new StorageLock(storageLockPath(env));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("DeclarationStore", () => {
  it("writes the default declaration on first load()", async () => {
    const store = new DeclarationStore(lock, env);
    const decl = await store.load();
    expect(decl.meta.contract).toBe("UCC");
    // Second call returns the persisted version (no rewrite needed).
    const again = await store.load();
    expect(again).toEqual(decl);
  });

  it("save() persists user mutations", async () => {
    const store = new DeclarationStore(lock, env);
    const decl = await store.load();
    decl.uic.preferences[0]!.value = "edited";
    await store.save(decl);
    const reloaded = await store.load();
    expect(reloaded.uic.preferences[0]!.value).toBe("edited");
  });
});

describe("StateStore", () => {
  it("returns the default state when no file exists", async () => {
    const store = new StateStore(lock, env);
    const s = await store.load();
    expect(s.paused).toBe(false);
    expect(s.session_id).toBeNull();
  });

  it("save() bumps _rev on each write", async () => {
    const store = new StateStore(lock, env);
    const s = await store.load();
    const a = await store.save(s);
    const b = await store.save(a);
    expect(a._rev).toBe(1);
    expect(b._rev).toBe(2);
  });

  it("update() applies a mutator and persists", async () => {
    const store = new StateStore(lock, env);
    const out = await store.update((s) => {
      s.paused = true;
      s.active_gid = "abc";
    });
    expect(out.paused).toBe(true);
    expect(out.active_gid).toBe("abc");
    expect(out._rev).toBe(1);
  });
});

describe("QueueStore + ArchiveStore", () => {
  it("round-trips queue items", async () => {
    const queue = new QueueStore(lock, env);
    expect(await queue.load()).toEqual([]);
    await queue.save([{ id: "a", url: "u", status: "queued" }, { id: "b", url: "u", status: "active" }]);
    const items = await queue.load();
    expect(items.map((i) => i.id)).toEqual(["a", "b"]);
  });

  it("archive append() stamps archived_at", async () => {
    const archive = new ArchiveStore(lock, env);
    await archive.append({ id: "x", url: "u", status: "complete" });
    const items = await archive.load();
    expect(items).toHaveLength(1);
    expect(typeof items[0]!.archived_at).toBe("string");
  });
});
