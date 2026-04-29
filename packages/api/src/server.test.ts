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
  app = buildServer({
    queueOps,
    queueStore: queue,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
    cwd: dir,
  });
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

describe("GET /api/preflight", () => {
  it("returns fail when aria2 is unreachable (no client wired)", async () => {
    const res = await app.inject({ method: "GET", url: "/api/preflight" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.status).toBe("fail");
    expect(body.hard_failures).toContain("aria2_available");
  });
});

describe("GET /api/active", () => {
  it("returns active=null with reason when no aria2 client is wired", async () => {
    const res = await app.inject({ method: "GET", url: "/api/active" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ ok: true, active: null, reason: "aria2_unavailable" });
  });
});

describe("session lifecycle endpoints", () => {
  it("/api/sessions/current returns null before any session is open", async () => {
    const res = await app.inject({ method: "GET", url: "/api/sessions/current" });
    expect(res.json()).toEqual({ ok: true, session: null });
  });

  it("opens a session via POST and reports it via /current with stats", async () => {
    const start = await app.inject({ method: "POST", url: "/api/sessions/start" });
    expect(start.statusCode).toBe(200);
    const sid = start.json().session.session_id;
    expect(typeof sid).toBe("string");
    const cur = await app.inject({ method: "GET", url: "/api/sessions/current" });
    const body = cur.json();
    expect(body.session.session_id).toBe(sid);
    expect(body.stats.session_id).toBe(sid);
  });

  it("close refuses while items are active (ASM CR-4)", async () => {
    await app.inject({ method: "POST", url: "/api/sessions/start" });
    // Add an item, then mark it active by writing the queue directly via
    // the storage path the server exposes — easiest is a fresh add (which
    // is queued) followed by close: queued items don't trip CR-4, so we
    // need to inject an active row. Use the queueOps to transition.
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    // Switch the row's status to "active" via the store directly (no
    // transition route is exposed yet).
    const id = add.json().items[0].id;
    const items = (await (await import("node:fs/promises")).readFile(`${dir}/queue.json`, "utf8"))
      .replace(/"queued"/g, '"active"');
    await (await import("node:fs/promises")).writeFile(`${dir}/queue.json`, items);
    const close = await app.inject({ method: "POST", url: "/api/sessions/close" });
    expect(close.statusCode).toBe(409);
    expect(close.json().error).toBe("session_close_blocked");
    // sanity: id round-trip
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("history is empty by default", async () => {
    const res = await app.inject({ method: "GET", url: "/api/sessions/history" });
    expect(res.json()).toEqual({ ok: true, history: [] });
  });
});

describe("PUT /api/declaration", () => {
  it("persists a mutated declaration accepted via the declaration key", async () => {
    const got = await app.inject({ method: "GET", url: "/api/declaration" });
    const decl = got.json().declaration;
    decl.uic.preferences[0].value = "edited";
    const put = await app.inject({
      method: "PUT",
      url: "/api/declaration",
      payload: { declaration: decl },
    });
    expect(put.statusCode).toBe(200);
    const reloaded = await app.inject({ method: "GET", url: "/api/declaration" });
    expect(reloaded.json().declaration.uic.preferences[0].value).toBe("edited");
  });

  it("400s on a missing meta / uic", async () => {
    const res = await app.inject({
      method: "PUT",
      url: "/api/declaration",
      payload: { declaration: { meta: {}, uic: {} } },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("invalid_declaration");
  });
});

describe("GET /api/actions", () => {
  it("returns recently appended action entries", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/actions" });
    const body = res.json();
    expect(body.ok).toBe(true);
    expect(Array.isArray(body.entries)).toBe(true);
    expect(body.entries.some((e: { action: string }) => e.action === "add")).toBe(true);
  });

  it("clamps the limit query into [1, 5000]", async () => {
    const r1 = await app.inject({ method: "GET", url: "/api/actions?limit=0" });
    expect(r1.json().limit).toBe(200);
    const r2 = await app.inject({ method: "GET", url: "/api/actions?limit=99999" });
    expect(r2.json().limit).toBe(5000);
  });
});

describe("404 handler", () => {
  it("returns the canonical not_found shape", async () => {
    const res = await app.inject({ method: "GET", url: "/api/nope" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({ ok: false, error: "not_found" });
  });
});
