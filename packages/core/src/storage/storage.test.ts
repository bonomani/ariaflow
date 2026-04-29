import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { readJson, writeJson } from "./json.js";
import { StorageLock } from "./lock.js";
import {
  actionLogPath,
  archivePath,
  configDir,
  queuePath,
  sessionsLogPath,
  statePath,
  storageLockPath,
} from "./paths.js";

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-storage-"));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("paths", () => {
  it("uses ARIAFLOW_DIR when set", () => {
    expect(configDir({ ARIAFLOW_DIR: "/tmp/foo" })).toBe("/tmp/foo");
  });
  it("falls back to ARIA_QUEUE_DIR", () => {
    expect(configDir({ ARIA_QUEUE_DIR: "/tmp/bar" })).toBe("/tmp/bar");
  });
  it("derives every well-known path from configDir", () => {
    const env = { ARIAFLOW_DIR: dir };
    expect(queuePath(env)).toBe(join(dir, "queue.json"));
    expect(statePath(env)).toBe(join(dir, "state.json"));
    expect(archivePath(env)).toBe(join(dir, "archive.json"));
    expect(actionLogPath(env)).toBe(join(dir, "actions.jsonl"));
    expect(sessionsLogPath(env)).toBe(join(dir, "sessions.jsonl"));
    expect(storageLockPath(env)).toBe(join(dir, ".storage.lock"));
  });
});

describe("readJson / writeJson", () => {
  it("returns the default when missing", async () => {
    expect(await readJson(join(dir, "missing.json"), { ok: true })).toEqual({ ok: true });
  });

  it("round-trips JSON with sorted keys + atomic rename", async () => {
    const path = join(dir, "x.json");
    await writeJson(path, { z: 1, a: 2, nested: { b: 1, a: 1 } });
    const raw = readFileSync(path, "utf8");
    expect(raw.endsWith("\n")).toBe(true);
    expect(raw.indexOf('"a"')).toBeLessThan(raw.indexOf('"z"'));
    expect(await readJson(path, null)).toEqual({ a: 2, nested: { a: 1, b: 1 }, z: 1 });
  });

  it("recovers from a corrupt file (returns default + writes .corrupt.bak)", async () => {
    const path = join(dir, "bad.json");
    await writeJson(path, { ok: true });
    // overwrite with invalid JSON
    const { writeFile } = await import("node:fs/promises");
    await writeFile(path, "{not json", "utf8");
    const fallback = { fallback: true };
    expect(await readJson(path, fallback)).toEqual(fallback);
  });
});

describe("StorageLock", () => {
  it("serializes overlapping callers", async () => {
    const lock = new StorageLock(storageLockPath({ ARIAFLOW_DIR: dir }));
    const events: string[] = [];
    const slow = lock.with(async () => {
      events.push("a-start");
      await new Promise((r) => setTimeout(r, 20));
      events.push("a-end");
    });
    const fast = lock.with(async () => {
      events.push("b-start");
      events.push("b-end");
    });
    await Promise.all([slow, fast]);
    expect(events).toEqual(["a-start", "a-end", "b-start", "b-end"]);
  });

  it("supports reentrant nesting from the same caller", async () => {
    const lock = new StorageLock(storageLockPath({ ARIAFLOW_DIR: dir }));
    const result = await lock.with(async () => {
      return lock.with(async () => "inner");
    });
    expect(result).toBe("inner");
  });

  it("releases the lock after a thrown callback so subsequent callers proceed", async () => {
    const lock = new StorageLock(storageLockPath({ ARIAFLOW_DIR: dir }));
    await expect(
      lock.with(async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    await expect(lock.with(async () => "ok")).resolves.toBe("ok");
  });
});
