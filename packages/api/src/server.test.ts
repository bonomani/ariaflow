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
  app = buildServer({ queueOps, queueStore: queue, declarationStore: declaration, cwd: dir });
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

describe("GET /api/downloads", () => {
  it("returns summary + items with allowed actions", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/a" }, { url: "http://h/b" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/downloads" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.summary.total).toBe(2);
    expect(body.summary.queued).toBe(2);
    expect(body.items).toHaveLength(2);
    expect(body.items[0].actions).toEqual(["pause", "remove"]);
  });
});

describe("GET /api/downloads/:id", () => {
  it("returns the item when present", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({ method: "GET", url: `/api/downloads/${id}` });
    expect(res.statusCode).toBe(200);
    expect(res.json().item.url).toBe("http://h/x");
  });

  it("400s on a non-UUID id", async () => {
    const res = await app.inject({ method: "GET", url: "/api/downloads/not-a-uuid" });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("invalid_id");
  });

  it("404s on an unknown id", async () => {
    const res = await app.inject({
      method: "GET",
      url: "/api/downloads/00000000-0000-0000-0000-000000000000",
    });
    expect(res.statusCode).toBe(404);
  });
});

describe("DELETE /api/downloads/:id", () => {
  it("removes an existing item", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const del = await app.inject({ method: "DELETE", url: `/api/downloads/${id}` });
    expect(del.statusCode).toBe(200);
    const list = await app.inject({ method: "GET", url: "/api/downloads" });
    expect(list.json().summary.total).toBe(0);
  });
});

describe("GET /api/declaration", () => {
  it("seeds and returns the default declaration on first read", async () => {
    const res = await app.inject({ method: "GET", url: "/api/declaration" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.declaration.meta.contract).toBe("UCC");
    expect(body.declaration.uic.gates).toHaveLength(2);
  });
});

describe("404 handler", () => {
  it("returns the canonical not_found shape", async () => {
    const res = await app.inject({ method: "GET", url: "/api/nope" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({ ok: false, error: "not_found" });
  });
});
