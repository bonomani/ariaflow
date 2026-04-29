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

describe("pause / resume routes", () => {
  it("POST /api/downloads/:id/pause flips status to paused", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({ method: "POST", url: `/api/downloads/${id}/pause` });
    expect(res.statusCode).toBe(200);
    expect(res.json().item.status).toBe("paused");
  });

  it("POST /api/downloads/:id/resume flips status back to queued", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/y" }] },
    });
    const id = add.json().items[0].id;
    await app.inject({ method: "POST", url: `/api/downloads/${id}/pause` });
    const res = await app.inject({ method: "POST", url: `/api/downloads/${id}/resume` });
    expect(res.json().item.status).toBe("queued");
    expect(typeof res.json().item.resumed_at).toBe("string");
  });

  it("400 on a non-UUID id, 404 on an unknown id", async () => {
    const bad = await app.inject({ method: "POST", url: "/api/downloads/x/pause" });
    expect(bad.statusCode).toBe(400);
    const miss = await app.inject({
      method: "POST",
      url: "/api/downloads/00000000-0000-0000-0000-000000000000/pause",
    });
    expect(miss.statusCode).toBe(404);
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

describe("GET /api/bandwidth", () => {
  it("returns the bandwidth config + null probe before any probe has run", async () => {
    const res = await app.inject({ method: "GET", url: "/api/bandwidth" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true);
    expect(body.config.probe_interval_seconds).toBeGreaterThanOrEqual(30);
    expect(body.config.down_use_percent).toBeCloseTo(0.8, 5);
    expect(body.config.up_use_percent).toBeCloseTo(0.5, 5);
    expect(body.last_probe).toBeNull();
    expect(body.cap_bytes_per_sec).toBeNull();
  });

  it("surfaces probe fields when the state already has a saved probe", async () => {
    // Inject a probe directly into state.json; the route does not
    // probe networkQuality itself.
    const { writeFileSync, mkdirSync } = await import("node:fs");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      `${dir}/state.json`,
      JSON.stringify({
        paused: false,
        active_gid: null,
        active_url: null,
        running: false,
        session_id: null,
        session_started_at: null,
        session_last_seen_at: null,
        session_closed_at: null,
        session_closed_reason: null,
        last_bandwidth_probe: {
          source: "networkquality",
          downlink_mbps: 100,
          uplink_mbps: 25,
          down_cap_mbps: 80,
          up_cap_mbps: 12.5,
          cap_bytes_per_sec: 10_000_000,
          interface_name: "en0",
          responsiveness_rpm: 740.4,
        },
        last_bandwidth_probe_at: 1_700_000_000,
      }),
    );
    const res = await app.inject({ method: "GET", url: "/api/bandwidth" });
    const body = res.json();
    expect(body.downlink_mbps).toBe(100);
    expect(body.up_cap_mbps).toBe(12.5);
    expect(body.cap_bytes_per_sec).toBe(10_000_000);
    expect(body.interface).toBe("en0");
    expect(body.last_probe_at).toBe(1_700_000_000);
  });
});

describe("GET /api/events (SSE)", () => {
  it("503s when no EventBus is wired", async () => {
    const res = await app.inject({ method: "GET", url: "/api/events" });
    expect(res.statusCode).toBe(503);
    expect(res.json().error).toBe("events_unavailable");
  });
});

describe("ActionLog -> EventBus bridge", () => {
  it("publishes 'action_logged' for each appended entry", async () => {
    const { ActionLog, ArchiveStore, DeclarationStore, EventBus, QueueOps, QueueStore, SessionService, StateStore, StorageLock, storageLockPath } =
      await import("@ariaflow/core");
    const { mkdtempSync, rmSync } = await import("node:fs");
    const { tmpdir } = await import("node:os");
    const { join } = await import("node:path");
    const local = mkdtempSync(join(tmpdir(), "ariaflow-bus-"));
    try {
      const env = { ARIAFLOW_DIR: local };
      const lock = new StorageLock(storageLockPath(env));
      const state = new StateStore(lock, env);
      const queue = new QueueStore(lock, env);
      const archive = new ArchiveStore(lock, env);
      const actions = new ActionLog(lock, state, env);
      const bus = new EventBus();
      actions.setBus(bus);
      const sessions = new SessionService(lock, state, queue, archive, env);
      const decl = new DeclarationStore(lock, env);
      const ops = new QueueOps(queue, sessions, decl, actions);
      const seen: Array<[string, unknown]> = [];
      bus.subscribe((event, data) => seen.push([event, data]));
      await ops.add({ url: "http://h/x" });
      const events = seen.map(([e]) => e);
      expect(events).toContain("action_logged");
    } finally {
      rmSync(local, { recursive: true, force: true });
    }
  });
});

describe("GET /api/health and /api/version", () => {
  it("/api/health is reachable with a numeric uptime", async () => {
    const res = await app.inject({ method: "GET", url: "/api/health" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true);
    expect(body.status).toBe("healthy");
    expect(typeof body.uptime_seconds).toBe("number");
  });

  it("/api/version surfaces the configured version, defaulting to 0.0.0", async () => {
    const res = await app.inject({ method: "GET", url: "/api/version" });
    expect(res.json()).toEqual({ ok: true, version: "0.0.0" });
  });
});

describe("GET /api/downloads/:id/files", () => {
  it("400 on a non-UUID id", async () => {
    const res = await app.inject({ method: "GET", url: "/api/downloads/bad/files" });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("invalid_id");
  });

  it("404 when the item doesn't exist", async () => {
    const res = await app.inject({
      method: "GET",
      url: "/api/downloads/00000000-0000-0000-0000-000000000000/files",
    });
    expect(res.statusCode).toBe(404);
  });

  it("409 when the item has no aria2 GID yet (still queued)", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({ method: "GET", url: `/api/downloads/${id}/files` });
    expect(res.statusCode).toBe(409);
    expect(res.json().error).toBe("no_gid");
  });

  it("returns aria2.getFiles when the gid is known and the client is wired", async () => {
    const mock = await mockServerWithAria2(dir, ({ method }) => {
      if (method === "aria2.getFiles") return [{ index: "1", path: "/x", length: "10" }];
      return "OK";
    });
    try {
      // Add an item, then write a gid into queue.json so the route resolves
      // it as "in flight". Calling QueueOps directly through the storage
      // stack the mock app shares avoids having to expose a transition route.
      const add = await mock.inject({
        method: "POST",
        url: "/api/downloads",
        payload: { items: [{ url: "http://h/y" }] },
      });
      const id = add.json().items[0].id;
      const queuePath = `${dir}/queue.json`;
      const { readFileSync, writeFileSync } = await import("node:fs");
      const data = JSON.parse(readFileSync(queuePath, "utf8"));
      data.items[0].gid = "GID42";
      writeFileSync(queuePath, JSON.stringify(data));
      const res = await mock.inject({ method: "GET", url: `/api/downloads/${id}/files` });
      expect(res.statusCode).toBe(200);
      const body = res.json();
      expect(body.gid).toBe("GID42");
      expect(body.files).toEqual([{ index: "1", path: "/x", length: "10" }]);
    } finally {
      await mock.close();
    }
  });
});

describe("aria2 option routes", () => {
  it("/api/aria2/option_tiers returns managed/safe sets and unsafe flag", async () => {
    const res = await app.inject({ method: "GET", url: "/api/aria2/option_tiers" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.managed).toContain("max-overall-download-limit");
    expect(body.safe).toContain("max-concurrent-downloads");
    expect(body.unsafe_enabled).toBe(false);
  });

  it("/api/aria2/global_option 503s when no aria2 client is wired", async () => {
    const res = await app.inject({ method: "GET", url: "/api/aria2/global_option" });
    expect(res.statusCode).toBe(503);
    expect(res.json().error).toBe("aria2_unavailable");
  });

  it("change_global_option rejects managed options before any RPC", async () => {
    const mock = await mockServerWithAria2(dir, () => ({}));
    try {
      const res = await mock.inject({
        method: "POST",
        url: "/api/aria2/change_global_option",
        payload: { "max-overall-download-limit": "1000" },
      });
      expect(res.statusCode).toBe(400);
      expect(res.json().error).toBe("managed_options");
    } finally {
      await mock.close();
    }
  });

  it("change_global_option round-trips safe options + records an action", async () => {
    const calls: Array<{ method: string; params: unknown[] }> = [];
    const mock = await mockServerWithAria2(dir, ({ method, params }) => {
      calls.push({ method, params });
      return method === "aria2.getGlobalOption" ? { x: "y" } : "OK";
    });
    try {
      const res = await mock.inject({
        method: "POST",
        url: "/api/aria2/change_global_option",
        payload: { "max-concurrent-downloads": 4 },
      });
      expect(res.statusCode).toBe(200);
      const change = calls.find((c) => c.method === "aria2.changeGlobalOption");
      expect(change!.params).toEqual([{ "max-concurrent-downloads": "4" }]);
    } finally {
      await mock.close();
    }
  });

  it("change_option 400s on missing gid/options", async () => {
    const mock = await mockServerWithAria2(dir, () => "OK");
    try {
      const res = await mock.inject({
        method: "POST",
        url: "/api/aria2/change_option",
        payload: { gid: "", options: {} },
      });
      expect(res.statusCode).toBe(400);
      expect(res.json().error).toBe("invalid_payload");
    } finally {
      await mock.close();
    }
  });

  it("option returns aria2.getOption keyed by gid", async () => {
    const mock = await mockServerWithAria2(dir, () => ({ split: "5" }));
    try {
      const res = await mock.inject({ method: "GET", url: "/api/aria2/option?gid=G1" });
      expect(res.json()).toMatchObject({ ok: true, gid: "G1", options: { split: "5" } });
    } finally {
      await mock.close();
    }
  });
});

async function mockServerWithAria2(
  baseDir: string,
  reply: (req: { method: string; params: unknown[] }) => unknown,
) {
  const fetchImpl = async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(init!.body as string) as { method: string; params: unknown[] };
    return new Response(
      JSON.stringify({ jsonrpc: "2.0", id: "x", result: reply(body) }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  };
  const {
    Aria2Client,
    StorageLock,
    storageLockPath,
    StateStore,
    QueueStore,
    ArchiveStore,
    ActionLog,
    SessionService,
    DeclarationStore,
    QueueOps,
  } = await import("@ariaflow/core");
  const env = { ARIAFLOW_DIR: baseDir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);
  const client = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
  return buildServer({
    queueOps,
    queueStore: queue,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
    aria2: client,
    cwd: baseDir,
  });
}

describe("GET /api/openapi", () => {
  it("returns the generated OpenAPI 3.0.3 doc with our routes tagged", async () => {
    const res = await app.inject({ method: "GET", url: "/api/openapi" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.openapi).toBe("3.0.3");
    expect(body.paths["/api/downloads"].post.tags).toEqual(["Queue"]);
    expect(body.paths["/api/declaration"].get.tags).toEqual(["Config"]);
    // The doc itself is a path, so it must show up too.
    expect(body.paths["/api/openapi"]).toBeTruthy();
  });
});

describe("404 handler", () => {
  it("returns the canonical not_found shape", async () => {
    const res = await app.inject({ method: "GET", url: "/api/nope" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({ ok: false, error: "not_found" });
  });
});
