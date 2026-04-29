import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  ActionLog,
  ArchiveStore,
  DeclarationStore,
  QueueOps,
  QueueStore,
  SessionService,
  StateStore,
  StorageLock,
  storageLockPath,
} from "@ariaflow/core";
import { buildServer } from "./server.js";

let dir: string;
let app: ReturnType<typeof buildServer>;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-api-"));
  const env = { ARIAFLOW_DIR: dir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);
  app = buildServer({ queueOps, cwd: dir });
});

afterEach(async () => {
  await app.close();
  rmSync(dir, { recursive: true, force: true });
});

describe("POST /api/downloads", () => {
  it("creates a queued item from a single-URL request", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/file.iso" }] },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { ok: boolean; items: Array<{ id: string; url: string; status: string; duplicate: boolean }> };
    expect(body.ok).toBe(true);
    expect(body.items).toHaveLength(1);
    expect(body.items[0]!.url).toBe("http://h/file.iso");
    expect(body.items[0]!.status).toBe("queued");
    expect(body.items[0]!.duplicate).toBe(false);
  });

  it("flags duplicates on a second add of the same URL", async () => {
    const send = () =>
      app.inject({
        method: "POST",
        url: "/api/downloads",
        payload: { items: [{ url: "http://h/dup" }] },
      });
    await send();
    const second = await send();
    expect(second.statusCode).toBe(200);
    expect(second.json().items[0].duplicate).toBe(true);
  });

  it("400s on invalid payload shape with the canonical error envelope", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/downloads",
      headers: { "content-type": "application/json" },
      payload: "null",
    });
    expect(res.statusCode).toBe(400);
    const body = res.json();
    expect(body).toMatchObject({ ok: false, error: "invalid_payload" });
  });

  it("400s on a bad URL scheme and pins the offending index", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/ok" }, { url: "file:///etc/passwd" }] },
    });
    expect(res.statusCode).toBe(400);
    const body = res.json();
    expect(body.error).toBe("invalid_url");
    expect(body.index).toBe(1);
  });
});

describe("404 handler", () => {
  it("returns the canonical not_found shape", async () => {
    const res = await app.inject({ method: "GET", url: "/api/nope" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({ ok: false, error: "not_found" });
  });
});
