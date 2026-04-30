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
    archiveStore: archive,
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

describe("POST /api/bandwidth/probe", () => {
  it("returns the default probe shape when networkQuality is unavailable", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/bandwidth/probe",
      payload: {},
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true);
    expect(body.probe.source).toBe("default");
    expect(body.probe.reason).toBe("probe_unavailable");
    expect(body.config.probe_interval_seconds).toBeGreaterThanOrEqual(30);
  });

  it("persists last_bandwidth_probe + records 'probe' action on each call", async () => {
    await app.inject({ method: "POST", url: "/api/bandwidth/probe", payload: {} });
    const status = await app.inject({ method: "GET", url: "/api/bandwidth" });
    const body = status.json();
    expect(body.last_probe).not.toBeNull();
    expect(typeof body.last_probe_at).toBe("number");
    const log = await app.inject({ method: "GET", url: "/api/actions" });
    expect(
      (log.json().entries as Array<{ action: string; target: string }>).some(
        (e) => e.action === "probe" && e.target === "bandwidth",
      ),
    ).toBe(true);
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

describe("GET /api/log", () => {
  it("returns {items: [...]} matching the Python route shape", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/log" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(Array.isArray(body.items)).toBe(true);
    expect(body.items.some((e: { action: string }) => e.action === "add")).toBe(true);
    // No `ok` / `limit` fields — that's /api/actions, not /api/log.
    expect(body.ok).toBeUndefined();
    expect(body.limit).toBeUndefined();
  });

  it("clamps limit into [1, 500]", async () => {
    // Push >5 entries to verify the clamp applies.
    for (let i = 0; i < 5; i++) {
      await app.inject({
        method: "POST",
        url: "/api/downloads",
        payload: { items: [{ url: `http://h/${i}` }] },
      });
    }
    const r = await app.inject({ method: "GET", url: "/api/log?limit=2" });
    expect(r.json().items.length).toBeLessThanOrEqual(2);
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

describe("POST /api/aria2/multicall", () => {
  it("503 when no aria2 client is wired", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/aria2/multicall",
      payload: { calls: [{ methodName: "aria2.tellActive" }] },
    });
    expect(res.statusCode).toBe(503);
  });

  it("400 on missing or empty calls", async () => {
    const mock = await mockServerWithAria2(dir, () => "OK");
    try {
      const r1 = await mock.inject({
        method: "POST",
        url: "/api/aria2/multicall",
        payload: { calls: [] },
      });
      expect(r1.statusCode).toBe(400);
      expect(r1.json().error).toBe("invalid_calls");
      const r2 = await mock.inject({
        method: "POST",
        url: "/api/aria2/multicall",
        payload: { calls: [{}] },
      });
      expect(r2.statusCode).toBe(400);
      expect(r2.json().error).toBe("invalid_call");
      expect(r2.json().index).toBe(0);
    } finally {
      await mock.close();
    }
  });

  it("forwards calls to system.multicall and returns the results array", async () => {
    const mock = await mockServerWithAria2(dir, ({ method, params }) => {
      if (method === "system.multicall") {
        const batch = params[0] as Array<{ methodName: string }>;
        return batch.map((c) => ({ ok: true, method: c.methodName }));
      }
      return [];
    });
    try {
      const res = await mock.inject({
        method: "POST",
        url: "/api/aria2/multicall",
        payload: {
          calls: [
            { methodName: "aria2.tellActive" },
            { methodName: "aria2.tellWaiting", params: [0, 50] },
          ],
        },
      });
      expect(res.statusCode).toBe(200);
      const body = res.json();
      expect(body.ok).toBe(true);
      expect(body.results).toEqual([
        { ok: true, method: "aria2.tellActive" },
        { ok: true, method: "aria2.tellWaiting" },
      ]);
    } finally {
      await mock.close();
    }
  });
});

describe("GET /api/tests", () => {
  it("returns the {ok, available:false, message} stub", async () => {
    const res = await app.inject({ method: "GET", url: "/api/tests" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ ok: true, available: false });
  });
});

describe("PATCH /api/declaration/preferences", () => {
  it("PATCH and POST are both wired and apply identically", async () => {
    const patch = await app.inject({
      method: "PATCH",
      url: "/api/declaration/preferences",
      payload: { max_simultaneous_downloads: 7 },
    });
    expect(patch.statusCode).toBe(200);
    expect(patch.json().applied.max_simultaneous_downloads).toEqual({
      before: 1,
      after: 7,
    });
    const post = await app.inject({
      method: "POST",
      url: "/api/declaration/preferences",
      payload: { max_simultaneous_downloads: 9 },
    });
    expect(post.json().applied.max_simultaneous_downloads).toEqual({
      before: 7,
      after: 9,
    });
  });
});

describe("POST /api/declaration/preferences", () => {
  it("400s on empty / non-object payload", async () => {
    const a = await app.inject({
      method: "POST",
      url: "/api/declaration/preferences",
      payload: {},
    });
    expect(a.statusCode).toBe(400);
    expect(a.json().error).toBe("invalid_payload");
  });

  it("400 unknown_preferences on a typo'd key", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/declaration/preferences",
      payload: { not_a_real_pref: 1 },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("unknown_preferences");
  });

  it("applies a single-key update and returns before/after", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/declaration/preferences",
      payload: { max_simultaneous_downloads: 3 },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.applied.max_simultaneous_downloads).toEqual({ before: 1, after: 3 });
    const reloaded = await app.inject({ method: "GET", url: "/api/declaration" });
    const pref = reloaded
      .json()
      .declaration.uic.preferences.find(
        (p: { name: string }) => p.name === "max_simultaneous_downloads",
      );
    expect(pref.value).toBe(3);
  });
});

describe("POST /api/downloads/:id/files", () => {
  it("400 on a non-array select", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({
      method: "POST",
      url: `/api/downloads/${id}/files`,
      payload: { select: "all" },
    });
    expect(res.statusCode).toBe(400);
  });

  it("writes selected_files to the queue row and records an action", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({
      method: "POST",
      url: `/api/downloads/${id}/files`,
      payload: { select: [1, 3, "5"] },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ ok: true, item_id: id, selected_files: [1, 3, 5] });
    const get = await app.inject({ method: "GET", url: `/api/downloads/${id}` });
    expect(get.json().item.selected_files).toEqual([1, 3, 5]);
  });

  it("404 on an unknown id", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/downloads/00000000-0000-0000-0000-000000000000/files",
      payload: { select: [1] },
    });
    expect(res.statusCode).toBe(404);
  });
});

describe("meta routes", () => {
  it("GET /api returns the discovery payload", async () => {
    const res = await app.inject({ method: "GET", url: "/api" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({
      name: "ariaflow-server",
      docs: "/api/docs",
      openapi: "/api/openapi.yaml",
    });
  });

  it("GET /api/docs serves the Swagger UI HTML page", async () => {
    const res = await app.inject({ method: "GET", url: "/api/docs" });
    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toMatch(/text\/html/);
    expect(res.body).toContain("SwaggerUIBundle");
    expect(res.body).toContain("/api/openapi.yaml");
  });

  it("GET /api/openapi.yaml 404s when not configured", async () => {
    const res = await app.inject({ method: "GET", url: "/api/openapi.yaml" });
    expect(res.statusCode).toBe(404);
  });

  it("GET /api/openapi.yaml serves the file when configured", async () => {
    const { writeFileSync } = await import("node:fs");
    const yamlPath = `${dir}/openapi.yaml`;
    writeFileSync(yamlPath, "openapi: 3.0.3\ninfo: {title: t, version: '0'}\npaths: {}\n");
    const sibling = await freshAppWithOpenApiYaml(dir, yamlPath);
    try {
      const res = await sibling.inject({ method: "GET", url: "/api/openapi.yaml" });
      expect(res.statusCode).toBe(200);
      expect(res.headers["content-type"]).toMatch(/yaml/);
      expect(res.body).toContain("openapi: 3.0.3");
    } finally {
      await sibling.close();
    }
  });

  it("GET /api/status returns items + summary + state", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/a" }, { url: "http://h/b" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/status" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.summary.total).toBe(2);
    expect(body.items).toHaveLength(2);
    expect(body.state).toBeDefined();
  });

  it("GET /api/status?status=queued filters and flips `filtered`", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/a" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/status?status=queued" });
    expect(res.json().filtered).toBe(true);
    const empty = await app.inject({ method: "GET", url: "/api/status?status=active" });
    expect(empty.json().items).toEqual([]);
  });
});

async function freshAppWithOpenApiYaml(baseDir: string, yamlPath: string) {
  const env = { ARIAFLOW_DIR: baseDir };
  const {
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
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);
  return buildServer({
    queueOps,
    queueStore: queue,
    archiveStore: archive,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
    openapiYamlPath: yamlPath,
    cwd: baseDir,
  });
}

describe("downloads compat aliases + cleanup", () => {
  it("POST /api/downloads/add behaves like POST /api/downloads", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/downloads/add",
      payload: { items: [{ url: "http://h/x" }] },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json().items[0].url).toBe("http://h/x");
  });

  it("POST /api/declaration behaves like PUT /api/declaration", async () => {
    const got = await app.inject({ method: "GET", url: "/api/declaration" });
    const decl = got.json().declaration;
    decl.uic.preferences[0].value = "edited-via-post";
    const res = await app.inject({
      method: "POST",
      url: "/api/declaration",
      payload: { declaration: decl },
    });
    expect(res.statusCode).toBe(200);
    const reloaded = await app.inject({ method: "GET", url: "/api/declaration" });
    expect(reloaded.json().declaration.uic.preferences[0].value).toBe("edited-via-post");
  });

  it("GET /api/downloads/archive returns {ok, items} (empty by default)", async () => {
    const res = await app.inject({ method: "GET", url: "/api/downloads/archive" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true, items: [] });
  });

  it("POST /api/downloads/cleanup archives stale terminal items + records action", async () => {
    const { writeFileSync } = await import("node:fs");
    const oldDate = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString();
    writeFileSync(
      `${dir}/queue.json`,
      JSON.stringify({
        items: [
          {
            id: "11111111-1111-1111-1111-111111111111",
            url: "http://h/x",
            status: "complete",
            completed_at: oldDate,
          },
          {
            id: "22222222-2222-2222-2222-222222222222",
            url: "http://h/y",
            status: "active",
          },
        ],
      }),
    );
    const res = await app.inject({
      method: "POST",
      url: "/api/downloads/cleanup",
      payload: { max_done_age_days: 7 },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ ok: true, archived: 1, remaining: 1 });
    const archive = await app.inject({ method: "GET", url: "/api/downloads/archive" });
    expect(archive.json().items).toHaveLength(1);
    expect(archive.json().items[0].id).toBe("11111111-1111-1111-1111-111111111111");
  });
});

describe("aria2 / sessions / remove compat aliases", () => {
  it("/api/aria2/get_global_option mirrors /api/aria2/global_option (503 unwired)", async () => {
    const a = await app.inject({ method: "GET", url: "/api/aria2/get_global_option" });
    const b = await app.inject({ method: "GET", url: "/api/aria2/global_option" });
    expect(a.statusCode).toBe(503);
    expect(b.statusCode).toBe(503);
  });

  it("/api/aria2/get_option mirrors /api/aria2/option (missing gid -> 503 first)", async () => {
    const res = await app.inject({ method: "GET", url: "/api/aria2/get_option" });
    expect(res.statusCode).toBe(503);
  });

  it("/api/sessions returns the same shape as /api/sessions/current minus stats", async () => {
    const before = await app.inject({ method: "GET", url: "/api/sessions" });
    expect(before.json()).toEqual({ ok: true, session: null });
    await app.inject({ method: "POST", url: "/api/sessions/start" });
    const after = await app.inject({ method: "GET", url: "/api/sessions" });
    expect(after.json().session.session_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(after.json().session.stats).toBeUndefined();
  });

  it("/api/sessions/stats returns the SessionService.stats() payload", async () => {
    await app.inject({ method: "POST", url: "/api/sessions/start" });
    const res = await app.inject({ method: "GET", url: "/api/sessions/stats" });
    expect(res.statusCode).toBe(200);
    expect(res.json().stats.session_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("POST /api/downloads/:id/remove behaves identically to DELETE /api/downloads/:id", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({ method: "POST", url: `/api/downloads/${id}/remove` });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true, id });
    const list = await app.inject({ method: "GET", url: "/api/downloads" });
    expect(list.json().summary.total).toBe(0);
  });

  it("POST /api/downloads/:id/remove 400 on bad id, 404 on miss", async () => {
    const bad = await app.inject({ method: "POST", url: "/api/downloads/notuuid/remove" });
    expect(bad.statusCode).toBe(400);
    const miss = await app.inject({
      method: "POST",
      url: "/api/downloads/00000000-0000-0000-0000-000000000000/remove",
    });
    expect(miss.statusCode).toBe(404);
  });
});

describe("priority / retry routes", () => {
  it("POST /:id/priority writes the new value and records an action", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({
      method: "POST",
      url: `/api/downloads/${id}/priority`,
      payload: { priority: 5 },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ ok: true, id, priority: 5 });
    const list = await app.inject({ method: "GET", url: "/api/downloads" });
    expect(list.json().items[0].id).toBe(id);
  });

  it("POST /:id/priority 400s on a non-numeric priority", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/y" }] },
    });
    const id = add.json().items[0].id;
    const res = await app.inject({
      method: "POST",
      url: `/api/downloads/${id}/priority`,
      payload: { priority: "high" },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("invalid_priority");
  });

  it("POST /:id/retry resets failure fields and bumps status back to queued", async () => {
    const add = await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/z" }] },
    });
    const id = add.json().items[0].id;
    // Inject an error state via the queue file directly (no scheduler yet).
    const { readFileSync, writeFileSync } = await import("node:fs");
    const data = JSON.parse(readFileSync(`${dir}/queue.json`, "utf8"));
    data.items[0].status = "error";
    data.items[0].error_code = "1";
    data.items[0].error_message = "boom";
    data.items[0].gid = "G1";
    writeFileSync(`${dir}/queue.json`, JSON.stringify(data));

    const res = await app.inject({ method: "POST", url: `/api/downloads/${id}/retry` });
    expect(res.statusCode).toBe(200);
    const item = res.json().item;
    expect(item.status).toBe("queued");
    expect(item.error_code).toBeNull();
    expect(item.error_message).toBeNull();
    expect(item.gid).toBeNull();
  });

  it("priority and retry both 404 on an unknown id", async () => {
    const fake = "00000000-0000-0000-0000-000000000000";
    const p = await app.inject({
      method: "POST",
      url: `/api/downloads/${fake}/priority`,
      payload: { priority: 1 },
    });
    const r = await app.inject({ method: "POST", url: `/api/downloads/${fake}/retry` });
    expect(p.statusCode).toBe(404);
    expect(r.statusCode).toBe(404);
  });
});

describe("POST /api/torrents/:infohash/stop", () => {
  it("404 when no active seed matches the infohash", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/torrents/missing/stop",
    });
    expect(res.statusCode).toBe(404);
  });

  it("flips distribute_status to stopped + records 'seed_stopped'", async () => {
    const { writeFileSync, existsSync } = await import("node:fs");
    const torrentPath = `${dir}/served.torrent`;
    writeFileSync(torrentPath, "BENCODED");
    writeFileSync(
      `${dir}/queue.json`,
      JSON.stringify({
        items: [
          {
            id: "11111111-1111-1111-1111-111111111111",
            url: "http://h/x.iso",
            distribute_status: "seeding",
            distribute_infohash: "abc123",
            distribute_torrent_path: torrentPath,
            distribute_seed_gid: "GID",
          },
        ],
      }),
    );
    const res = await app.inject({
      method: "POST",
      url: "/api/torrents/abc123/stop",
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true, infohash: "abc123", status: "stopped" });
    expect(existsSync(torrentPath)).toBe(false);
    const log = await app.inject({ method: "GET", url: "/api/actions" });
    const entries = log.json().entries as Array<{ action: string }>;
    expect(entries.some((e) => e.action === "seed_stopped")).toBe(true);
  });
});

describe("torrent serving routes", () => {
  it("GET /api/torrents lists only items in distribute_status=seeding", async () => {
    const { writeFileSync } = await import("node:fs");
    writeFileSync(
      `${dir}/queue.json`,
      JSON.stringify({
        items: [
          {
            id: "11111111-1111-1111-1111-111111111111",
            url: "http://h/x.iso",
            output: "x.iso",
            distribute_status: "seeding",
            distribute_infohash: "abc",
            distribute_torrent_path: "/tmp/missing.torrent",
            distribute_started_at: "2026-04-30T00:00:00Z",
            distribute_seed_gid: "GID",
          },
          {
            id: "22222222-2222-2222-2222-222222222222",
            url: "http://h/y.iso",
            distribute_status: "stopped",
            distribute_infohash: "def",
          },
        ],
      }),
    );
    const res = await app.inject({ method: "GET", url: "/api/torrents" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.count).toBe(1);
    expect(body.torrents[0]).toMatchObject({
      infohash: "abc",
      name: "x.iso",
      torrent_url: "/api/torrents/abc.torrent",
    });
  });

  it("GET /api/torrents/:infohash.torrent serves the file body", async () => {
    const { writeFileSync } = await import("node:fs");
    const torrentPath = `${dir}/served.torrent`;
    writeFileSync(torrentPath, "BENCODED");
    writeFileSync(
      `${dir}/queue.json`,
      JSON.stringify({
        items: [
          {
            id: "11111111-1111-1111-1111-111111111111",
            url: "http://h/x.iso",
            distribute_status: "seeding",
            distribute_infohash: "abc123",
            distribute_torrent_path: torrentPath,
          },
        ],
      }),
    );
    const res = await app.inject({ method: "GET", url: "/api/torrents/abc123.torrent" });
    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toBe("application/x-bittorrent");
    expect(res.body).toBe("BENCODED");
  });

  it("404 when the suffix is missing or the file isn't on disk", async () => {
    const noSuffix = await app.inject({ method: "GET", url: "/api/torrents/abc" });
    expect(noSuffix.statusCode).toBe(404);
    const { writeFileSync } = await import("node:fs");
    writeFileSync(
      `${dir}/queue.json`,
      JSON.stringify({
        items: [
          {
            id: "11111111-1111-1111-1111-111111111111",
            url: "http://h/x.iso",
            distribute_status: "seeding",
            distribute_infohash: "ghost",
            distribute_torrent_path: "/tmp/does-not-exist.torrent",
          },
        ],
      }),
    );
    const missing = await app.inject({ method: "GET", url: "/api/torrents/ghost.torrent" });
    expect(missing.statusCode).toBe(404);
  });
});

describe("GET /api/peers", () => {
  it("returns an empty list when no registry is wired", async () => {
    const res = await app.inject({ method: "GET", url: "/api/peers" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true, peers: [] });
  });

  it("surfaces upserted peers when a registry is wired", async () => {
    const { PeerRegistry } = await import("@ariaflow/core");
    const registry = new PeerRegistry();
    registry.upsert({
      instance: "bc-mac",
      status: "browsed",
      last_seen: 1_700_000_000,
    });
    registry.upsert({
      instance: "bc-pi",
      host: "bc-pi.local",
      port: 8000,
      path: "/api",
      tls: false,
      base_url: "http://bc-pi.local:8000/api",
      last_seen: 1_700_000_000,
      status: "discovered",
    });
    const sibling = await freshAppWithPeerRegistry(dir, registry);
    try {
      const res = await sibling.inject({ method: "GET", url: "/api/peers" });
      const body = res.json();
      expect(body.peers).toHaveLength(2);
      expect(body.peers.map((p: { instance: string }) => p.instance)).toEqual([
        "bc-mac",
        "bc-pi",
      ]);
    } finally {
      await sibling.close();
    }
  });
});

async function freshAppWithPeerRegistry(
  baseDir: string,
  registry: import("@ariaflow/core").PeerRegistry,
) {
  const env = { ARIAFLOW_DIR: baseDir };
  const {
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
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);
  return buildServer({
    queueOps,
    queueStore: queue,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
    archiveStore: archive,
    peerRegistry: registry,
    cwd: baseDir,
  });
}

describe("scheduler routes", () => {
  it("GET /api/scheduler reports 'starting' before any run is started", async () => {
    const res = await app.inject({ method: "GET", url: "/api/scheduler" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.status).toBe("starting");
    expect(body.running).toBe(false);
    expect(body.paused).toBe(false);
  });

  it("pause then resume flips state.paused and bumps _rev each time", async () => {
    const before = await app.inject({ method: "GET", url: "/api/scheduler" });
    const pause = await app.inject({ method: "POST", url: "/api/scheduler/pause" });
    expect(pause.json().paused).toBe(true);
    expect(pause.json()._rev).toBeGreaterThan(before.json()._rev);
    const resume = await app.inject({ method: "POST", url: "/api/scheduler/resume" });
    expect(resume.json().paused).toBe(false);
    expect(resume.json()._rev).toBeGreaterThan(pause.json()._rev);
  });

  it("each pause/resume records an action entry", async () => {
    await app.inject({ method: "POST", url: "/api/scheduler/pause" });
    await app.inject({ method: "POST", url: "/api/scheduler/resume" });
    const log = await app.inject({ method: "GET", url: "/api/actions" });
    const entries = log.json().entries as Array<{ action: string; target: string }>;
    const schedulerEvents = entries.filter((e) => e.target === "scheduler");
    expect(schedulerEvents.map((e) => e.action)).toEqual(
      expect.arrayContaining(["pause", "resume"]),
    );
  });

  it("POST /api/scheduler/ucc returns failed envelope when preflight gates fail", async () => {
    const res = await app.inject({ method: "POST", url: "/api/scheduler/ucc" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.meta).toEqual({ contract: "UCC", version: "2.0" });
    expect(body.result).toMatchObject({
      observation: "failed",
      outcome: "failed",
      failure_class: "permanent",
      reason: "gate_failed",
    });
    expect(body.preflight.hard_failures).toContain("aria2_available");
  });

  it("POST /api/scheduler/ucc records a 'ucc' action entry", async () => {
    await app.inject({ method: "POST", url: "/api/scheduler/ucc" });
    const log = await app.inject({ method: "GET", url: "/api/actions" });
    const entries = log.json().entries as Array<{ action: string; outcome: string }>;
    const ucc = entries.find((e) => e.action === "ucc");
    expect(ucc).toBeDefined();
    expect(ucc!.outcome).toBe("failed");
  });

  it("POST /api/scheduler/preflight returns the gate result and logs an action", async () => {
    const res = await app.inject({ method: "POST", url: "/api/scheduler/preflight" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    // No aria2 wired -> the readiness gate fails.
    expect(body.status).toBe("fail");
    expect(body.hard_failures).toContain("aria2_available");
    const log = await app.inject({ method: "GET", url: "/api/actions" });
    const entries = log.json().entries as Array<{ action: string; outcome: string }>;
    const last = entries.find((e) => e.action === "preflight");
    expect(last).toBeDefined();
    expect(last!.outcome).toBe("blocked");
  });
});

describe("POST /api/lifecycle/:target/:action", () => {
  it("400 unsupported_action on an unknown target/action pair", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/lifecycle/random/explode",
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("unsupported_action");
  });

  it("dry-run install returns the generated plan without spawning", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/lifecycle/aria2-service/install?dry_run=1",
    });
    if (res.statusCode === 200) {
      const body = res.json();
      expect(body.dry_run).toBe(true);
      const target = Object.keys(body.result)[0]!;
      expect(["aria2-launchd", "aria2-systemd"]).toContain(target);
      expect(body.result[target].ok).toBe(true);
      expect(Array.isArray(body.result[target].commands)).toBe(true);
    } else {
      // Unsupported platform — route surfaces a structured 500.
      expect(res.statusCode).toBe(500);
      expect(res.json().error).toBe("lifecycle_action_failed");
    }
  });
});

describe("GET /api/lifecycle", () => {
  it("returns ariaflow_server + networkquality status and session fields", async () => {
    const res = await app.inject({ method: "GET", url: "/api/lifecycle" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true);
    expect(body.ariaflow_server).toMatchObject({ installed: true, version: "0.0.0" });
    expect(body.networkquality).toHaveProperty("installed");
    expect(body.networkquality).toHaveProperty("reason");
    expect(body.session_id).toBeNull();
    expect(body.session_closed_at).toBeNull();
  });

  it("surfaces the open session_id once one exists", async () => {
    await app.inject({ method: "POST", url: "/api/sessions/start" });
    const res = await app.inject({ method: "GET", url: "/api/lifecycle" });
    expect(res.json().session_id).toMatch(/^[0-9a-f-]{36}$/);
  });
});

describe("POST /api/aria2/set_limits", () => {
  it("503 when no aria2 client is wired", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/api/aria2/set_limits",
      payload: { max_overall_download_limit: 1000 },
    });
    expect(res.statusCode).toBe(503);
  });

  it("400 on a non-object payload", async () => {
    const mock = await mockServerWithAria2(dir, () => "OK");
    try {
      const res = await mock.inject({
        method: "POST",
        url: "/api/aria2/set_limits",
        payload: "null",
        headers: { "content-type": "application/json" },
      });
      expect(res.statusCode).toBe(400);
    } finally {
      await mock.close();
    }
  });

  it("calls the matching change_global_option keys for overall + seed limits", async () => {
    const calls: Array<{ method: string; params: unknown[] }> = [];
    const mock = await mockServerWithAria2(dir, ({ method, params }) => {
      calls.push({ method, params });
      return "OK";
    });
    try {
      const res = await mock.inject({
        method: "POST",
        url: "/api/aria2/set_limits",
        payload: {
          max_overall_download_limit: 125000,
          max_overall_upload_limit: 50000,
          seed_ratio: 1.5,
          seed_time: 60,
        },
      });
      expect(res.statusCode).toBe(200);
      const body = res.json();
      expect(body.ok).toBe(true);
      expect(body.errors).toEqual([]);
      // Each setter routes through aria2.changeGlobalOption with one key.
      const opts = calls
        .filter((c) => c.method === "aria2.changeGlobalOption")
        .map((c) => Object.keys(c.params[0] as object)[0]);
      expect(opts.sort()).toEqual([
        "max-overall-download-limit",
        "max-overall-upload-limit",
        "seed-ratio",
        "seed-time",
      ]);
    } finally {
      await mock.close();
    }
  });

  it("per-gid limits route through aria2.changeOption with the supplied gid", async () => {
    const calls: Array<{ method: string; params: unknown[] }> = [];
    const mock = await mockServerWithAria2(dir, ({ method, params }) => {
      calls.push({ method, params });
      return "OK";
    });
    try {
      await mock.inject({
        method: "POST",
        url: "/api/aria2/set_limits",
        payload: { gid: "G1", max_download_limit: 200000, max_upload_limit: 100000 },
      });
      const optionCalls = calls.filter((c) => c.method === "aria2.changeOption");
      expect(optionCalls.map((c) => c.params[0])).toEqual(["G1", "G1"]);
    } finally {
      await mock.close();
    }
  });

  it("collects per-key errors for non-numeric values", async () => {
    const mock = await mockServerWithAria2(dir, () => "OK");
    try {
      const res = await mock.inject({
        method: "POST",
        url: "/api/aria2/set_limits",
        payload: { max_overall_download_limit: "not-a-number" },
      });
      expect(res.statusCode).toBe(200);
      const body = res.json();
      expect(body.ok).toBe(false);
      expect(body.errors).toContain("max_overall_download_limit");
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
    archiveStore: archive,
    aria2: client,
    cwd: baseDir,
  });
}

describe("OpenAPI path-template override", () => {
  it("emits /api/torrents/{infohash}.torrent (not /{file}) for the .torrent serve route", async () => {
    const res = await app.inject({ method: "GET", url: "/api/openapi" });
    const doc = res.json();
    expect(doc.paths["/api/torrents/{infohash}.torrent"]).toBeDefined();
    expect(doc.paths["/api/torrents/{file}"]).toBeUndefined();
  });
});

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

describe("CORS", () => {
  it("echoes the request Origin on /api/* responses by default", async () => {
    const res = await app.inject({
      method: "GET",
      url: "/api/health",
      headers: { origin: "http://dashboard.local" },
    });
    expect(res.statusCode).toBe(200);
    expect(res.headers["access-control-allow-origin"]).toBe("http://dashboard.local");
  });

  it("OPTIONS preflight returns the configured methods + allowed headers", async () => {
    const res = await app.inject({
      method: "OPTIONS",
      url: "/api/downloads",
      headers: {
        origin: "http://dashboard.local",
        "access-control-request-method": "POST",
        "access-control-request-headers": "content-type",
      },
    });
    expect([200, 204]).toContain(res.statusCode);
    expect(res.headers["access-control-allow-methods"]).toMatch(/POST/);
    expect(res.headers["access-control-allow-headers"]).toMatch(/Content-Type/);
  });
});

describe("404 handler", () => {
  it("returns the canonical not_found shape", async () => {
    const res = await app.inject({ method: "GET", url: "/api/nope" });
    expect(res.statusCode).toBe(404);
    expect(res.json()).toMatchObject({ ok: false, error: "not_found" });
  });
});
