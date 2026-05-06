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
let app: Awaited<ReturnType<typeof buildServer>>;

beforeEach(async () => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-api-"));
  app = (await makeWiredServer(dir)).app;
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
    expect(res.json()).toMatchObject({ ok: true, session: null });
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
    expect(res.json()).toMatchObject({ ok: true, history: [] });
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
    expect(body.current_limit).toBeNull();
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
          cap_mbps: 80,
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
    expect(body.current_limit).toBe(10_000_000);
    expect(body.last_probe_at).toBe(1_700_000_000);

    // BG-21: dashboard reads bw.interface_name / bw.source /
    // bw.current_limit / bw.cap_mbps at the top level.
    expect(body.interface_name).toBe("en0");
    expect(body.source).toBe("networkquality");
    expect(body.cap_mbps).toBe(80);
    expect(body.current_limit).toBe(10_000_000);
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

// R-T: every StateStore.update / .save publishes a "state_changed"
// frame on the wired EventBus so /api/events SSE clients see scheduler
// / run / pause flips live.
describe("StateStore -> EventBus bridge", () => {
  it("publishes 'state_changed' on update and save", async () => {
    const { EventBus, StateStore, StorageLock, storageLockPath } = await import(
      "@ariaflow/core"
    );
    const env = { ARIAFLOW_DIR: dir };
    const lock = new StorageLock(storageLockPath(env));
    const state = new StateStore(lock, env);
    const bus = new EventBus();
    state.setBus(bus);
    const seen: Array<[string, unknown]> = [];
    bus.subscribe((event, data) => seen.push([event, data]));
    await state.update((s) => {
      s.running = true;
    });
    await state.save({
      paused: false,
      active_gid: null,
      active_url: null,
      running: false,
      session_id: null,
      session_started_at: null,
      session_last_seen_at: null,
      session_closed_at: null,
      session_closed_reason: null,
    });
    expect(seen.filter(([e]) => e === "state_changed")).toHaveLength(2);
  });

  // BG-33: internal-only `paused` must NOT leak onto the SSE wire.
  // state_changed events strip it and stamp `dispatch_paused` instead.
  it("state_changed publishes the sanitized wire shape (no `paused`, has `dispatch_paused`)", async () => {
    const { EventBus, StateStore, StorageLock, storageLockPath } = await import(
      "@ariaflow/core"
    );
    const env = { ARIAFLOW_DIR: dir };
    const lock = new StorageLock(storageLockPath(env));
    const state = new StateStore(lock, env);
    const bus = new EventBus();
    state.setBus(bus);
    let payload: Record<string, unknown> | null = null;
    bus.subscribe((event, data) => {
      if (event === "state_changed") payload = data as Record<string, unknown>;
    });
    await state.update((s) => {
      s.paused = true;
      s.running = true;
    });
    expect(payload).not.toBeNull();
    expect(payload).not.toHaveProperty("paused");
    expect(payload).toMatchObject({ dispatch_paused: true, running: true });
  });

  // toWireState picks declared fields explicitly so internal-only flags
  // (scheduler_intent) and stale index-signature keys (e.g. last_error
  // from retired code paths) don't leak onto the wire.
  it("state_changed payload omits scheduler_intent and unknown index-signature keys", async () => {
    const { EventBus, StateStore, StorageLock, storageLockPath } = await import(
      "@ariaflow/core"
    );
    const env = { ARIAFLOW_DIR: dir };
    const lock = new StorageLock(storageLockPath(env));
    const state = new StateStore(lock, env);
    const bus = new EventBus();
    state.setBus(bus);
    let payload: Record<string, unknown> | null = null;
    bus.subscribe((event, data) => {
      if (event === "state_changed") payload = data as Record<string, unknown>;
    });
    await state.update((s) => {
      s.scheduler_intent = "running";
      // Simulate a stale field riding through the index signature.
      (s as Record<string, unknown>).last_error = "from a retired code path";
      (s as Record<string, unknown>).stop_requested = true;
    });
    expect(payload).not.toBeNull();
    expect(payload).not.toHaveProperty("scheduler_intent");
    expect(payload).not.toHaveProperty("last_error");
    expect(payload).not.toHaveProperty("stop_requested");
  });

  it("buildServer attaches the EventBus to StateStore so route mutations stream via SSE", async () => {
    const { EventBus } = await import("@ariaflow/core");
    const bus = new EventBus();
    const { app: wired, state } = await makeWiredServer(dir, { eventBus: bus });
    try {
      const seen: string[] = [];
      bus.subscribe((event) => seen.push(event));
      await state.update((s) => {
        s.scheduler_intent = "running";
      });
      expect(seen).toContain("state_changed");
    } finally {
      await wired.close();
    }
  });
});

describe("GET /api/log", () => {
  it("returns {ok: true, items: [...]} matching the canonical envelope", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/x" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/log" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true); // BG-24 cosmetic nit: was undefined.
    expect(Array.isArray(body.items)).toBe(true);
    expect(body.items.some((e: { action: string }) => e.action === "add")).toBe(true);
    // /api/log doesn't carry the `limit` echo — that's /api/actions.
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
  it("/api/health is reachable with a numeric uptime; classified bootstrap", async () => {
    const res = await app.inject({ method: "GET", url: "/api/health" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true);
    expect(body.status).toBe("healthy");
    expect(typeof body.uptime_seconds).toBe("number");
    expect(body.meta).toEqual({ freshness: "bootstrap" });
  });

  it("/api/version surfaces the configured version; classified bootstrap", async () => {
    const res = await app.inject({ method: "GET", url: "/api/version" });
    expect(res.json()).toMatchObject({ ok: true, version: "0.0.0" });
    expect(res.json().meta).toEqual({ freshness: "bootstrap" });
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
  it("400s on empty / non-object payload", async () => {
    const a = await app.inject({
      method: "PATCH",
      url: "/api/declaration/preferences",
      payload: {},
    });
    expect(a.statusCode).toBe(400);
    expect(a.json().error).toBe("invalid_payload");
  });

  it("400 unknown_preferences on a typo'd key", async () => {
    const res = await app.inject({
      method: "PATCH",
      url: "/api/declaration/preferences",
      payload: { not_a_real_pref: 1 },
    });
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("unknown_preferences");
  });

  it("applies a single-key update and returns before/after", async () => {
    const res = await app.inject({
      method: "PATCH",
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

  // R-J: openapi.yaml is now always served (generated by
  // @fastify/swagger from registered route schemas). No more
  // openapiYamlPath dependency.
  it("GET /api/openapi.yaml serves the generated YAML doc", async () => {
    const res = await app.inject({ method: "GET", url: "/api/openapi.yaml" });
    expect(res.statusCode).toBe(200);
    expect(res.headers["content-type"]).toMatch(/yaml/);
    expect(res.body).toMatch(/openapi:\s*3\.0/);
  });

  // BG-37 / R-J: info.version reflects deps.version (passed to
  // buildServer → @fastify/swagger's openapi.info at register time).
  it("GET /api/openapi.yaml stamps info.version to match /api/version", async () => {
    const sibling = await freshAppWithVersion(dir, "0.1.244");
    try {
      const yamlRes = await sibling.inject({ method: "GET", url: "/api/openapi.yaml" });
      const versionRes = await sibling.inject({ method: "GET", url: "/api/version" });
      expect(yamlRes.statusCode).toBe(200);
      expect(yamlRes.body).toContain("version: 0.1.244");
      expect(versionRes.json().version).toBe("0.1.244");
    } finally {
      await sibling.close();
    }
  });

  it("GET /api/status returns items + summary + state + identity", async () => {
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
    // BG-19: identity sub-object must be populated for the dashboard
    // header pills and offline-state gate.
    expect(body["ariaflow-server"]).toEqual({
      reachable: true,
      pid: expect.any(Number),
      version: "0.0.0",
      error: null,
    });
    expect(body.ok).toBe(true);
    expect(typeof body._rev).toBe("number");

    // BG-24: Developer-tab health chips. uptime is a non-negative
    // float, the four counters are non-negative integers, sse_clients
    // is 0 (no /api/events open in this test), disk_ok is a boolean.
    expect(typeof body.health.uptime_seconds).toBe("number");
    expect(body.health.uptime_seconds).toBeGreaterThanOrEqual(0);
    expect(typeof body.health.requests_total).toBe("number");
    expect(typeof body.health.errors_total).toBe("number");
    expect(body.health.sse_clients).toBe(0);
    expect(typeof body.health.bytes_received_total).toBe("number");
    expect(typeof body.health.bytes_sent_total).toBe("number");
    expect(typeof body.health.disk_ok).toBe("boolean");
  });

  it("BG-31: GET /api/_meta lists registered endpoints; revalidate_on references real routes", async () => {
    const res = await app.inject({ method: "GET", url: "/api/_meta" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true);
    expect(body.meta).toEqual({ freshness: "bootstrap" });
    expect(Array.isArray(body.endpoints)).toBe(true);
    const paths = body.endpoints.map((e: { path: string }) => e.path);
    expect(paths).toContain("/api/status");
    expect(paths).toContain("/api/_meta");

    const recorded = (app as unknown as { _ariaflowRoutes: Array<{ method: string | string[]; url: string }> })
      ._ariaflowRoutes;
    const known = new Set<string>();
    for (const r of recorded) {
      const methods = Array.isArray(r.method) ? r.method : [r.method];
      for (const m of methods) known.add(`${m} ${r.url}`);
    }
    for (const ep of body.endpoints) {
      for (const trigger of ep.revalidate_on ?? []) {
        expect(known.has(trigger)).toBe(true);
      }
    }
  });

  it("BG-31/BG-32: GET /api/status carries meta.freshness=live with transport_topics", async () => {
    const res = await app.inject({ method: "GET", url: "/api/status" });
    expect(res.json().meta).toEqual({
      freshness: "live",
      transport: "sse",
      transport_topics: ["items", "scheduler"],
    });
  });

  it("BG-32: /api/_meta surfaces transport_topics for live endpoints", async () => {
    const res = await app.inject({ method: "GET", url: "/api/_meta" });
    const status = res.json().endpoints.find((e: { path: string }) => e.path === "/api/status");
    expect(status.transport_topics).toEqual(["items", "scheduler"]);
  });

  it("BG-33/BG-35: GET /api/status surfaces canonical state.dispatch_paused only (no top-level, no legacy state.paused)", async () => {
    const res = await app.inject({ method: "GET", url: "/api/status" });
    const body = res.json();
    expect(body.state.dispatch_paused).toBe(false);
    expect(body).not.toHaveProperty("dispatch_paused");
    expect(body.state).not.toHaveProperty("paused");
  });

  it("BG-33: GET /api/status summary uses canonical removed (no legacy summary.stopped)", async () => {
    const res = await app.inject({ method: "GET", url: "/api/status" });
    const body = res.json();
    expect(body.summary).toHaveProperty("removed");
    expect(body.summary).not.toHaveProperty("stopped");
  });

  it("BG-35: GET /api/status?status=queued filters items; no `filtered` flag in payload", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/a" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/status?status=queued" });
    expect(res.json()).not.toHaveProperty("filtered");
    expect(res.json().items.length).toBeGreaterThan(0);
    const empty = await app.inject({ method: "GET", url: "/api/status?status=active" });
    expect(empty.json().items).toEqual([]);
  });
});

// Stub bandwidth probe: returns the same default-shape the real probe
// emits when `networkQuality` is missing. Avoids spawning the macOS
// binary (which can take 10s+) during tests.
const stubBandwidthProbe: typeof import("@ariaflow/core").runBandwidthProbe = async ({
  config,
}) => ({
  source: "default",
  reason: "probe_unavailable",
  downlink_mbps: null,
  cap_mbps: 1,
  cap_bytes_per_sec: 125_000,
  interval_seconds: config.probe_interval_seconds,
  down_cap_mbps: null,
  up_cap_mbps: null,
});

/**
 * Build the storage stack + a Fastify server bound to it under a given
 * temp dir. Override any ServerDeps via `overrides`. Returns the app
 * plus the live store handles so tests can manipulate state, queue,
 * etc. between requests.
 */
type ServerOverrides = Partial<Parameters<typeof buildServer>[0]>;
interface WiredServer {
  app: Awaited<ReturnType<typeof buildServer>>;
  state: StateStore;
  queue: QueueStore;
  archive: ArchiveStore;
  actions: ActionLog;
  sessions: SessionService;
  declaration: DeclarationStore;
}
async function makeWiredServer(baseDir: string, overrides: ServerOverrides = {}): Promise<WiredServer> {
  const env = { ARIAFLOW_DIR: baseDir };
  const lock = new StorageLock(storageLockPath(env));
  const state = new StateStore(lock, env);
  const queue = new QueueStore(lock, env);
  const archive = new ArchiveStore(lock, env);
  const actions = new ActionLog(lock, state, env);
  const sessions = new SessionService(lock, state, queue, archive, env);
  const declaration = new DeclarationStore(lock, env);
  const queueOps = new QueueOps(queue, sessions, declaration, actions);
  const app = await buildServer({
    queueOps,
    queueStore: queue,
    archiveStore: archive,
    declarationStore: declaration,
    stateStore: state,
    sessionService: sessions,
    actionLog: actions,
    cwd: baseDir,
    runBandwidthProbe: stubBandwidthProbe,
    ...overrides,
  });
  return { app, state, queue, archive, actions, sessions, declaration };
}

async function freshAppWithVersion(baseDir: string, version: string) {
  return (await makeWiredServer(baseDir, { version })).app;
}

describe("downloads compat aliases + cleanup", () => {
  it("GET /api/downloads/archive returns {ok, items} (empty by default)", async () => {
    const res = await app.inject({ method: "GET", url: "/api/downloads/archive" });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ ok: true, items: [] });
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
  it("/api/sessions returns the same shape as /api/sessions/current minus stats", async () => {
    const before = await app.inject({ method: "GET", url: "/api/sessions" });
    expect(before.json()).toMatchObject({ ok: true, session: null });
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
    expect(body.ok).toBe(true);
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
    expect(res.json()).toMatchObject({ ok: true, peers: [] });
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
  return (await makeWiredServer(baseDir, { peerRegistry: registry })).app;
}

describe("scheduler routes", () => {
  // BG-40: status enum is now stopped|starting|idle|running|paused.
  // A fresh state has scheduler_intent default of "stopped", so the
  // status must be "stopped" before any /start (or /resume) hits.
  it("GET /api/scheduler reports 'stopped' before any run is started", async () => {
    const res = await app.inject({ method: "GET", url: "/api/scheduler" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.status).toBe("stopped");
    expect(body.wait_reason).toBeNull();
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

  // Operator semantic: scheduler/pause freezes everything including
  // in-flight aria2 transfers (not just future dispatches). Symmetric
  // /resume calls aria2.unpauseAll. Best-effort RPC — an unreachable
  // daemon must not poison the state flip.
  it("/api/scheduler/pause and /resume call aria2.{pause,unpause}All when wired", async () => {
    const calls: string[] = [];
    const mock = await mockServerWithAria2(dir, ({ method }) => {
      calls.push(method);
      return "OK";
    });
    try {
      await mock.inject({ method: "POST", url: "/api/scheduler/pause" });
      await mock.inject({ method: "POST", url: "/api/scheduler/resume" });
    } finally {
      await mock.close();
    }
    expect(calls).toContain("aria2.pauseAll");
    expect(calls).toContain("aria2.unpauseAll");
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

  it("POST /api/scheduler/ucc records a 'contract' action entry (BG-48)", async () => {
    await app.inject({ method: "POST", url: "/api/scheduler/ucc" });
    const log = await app.inject({ method: "GET", url: "/api/actions" });
    const entries = log.json().entries as Array<{ action: string; outcome: string }>;
    const entry = entries.find((e) => e.action === "contract");
    expect(entry).toBeDefined();
    expect(entry!.outcome).toBe("failed");
  });

  it("POST /api/scheduler/contract is the BG-48 alias and emits the same shape", async () => {
    const res = await app.inject({ method: "POST", url: "/api/scheduler/contract" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.meta).toEqual({ contract: "UCC", version: "2.0" });
    expect(body.preflight).toBeDefined();
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

describe("BG-49: scheduler action endpoints return canonical state envelope", () => {
  it("POST /api/scheduler/pause returns canonical state envelope", async () => {
    const res = await app.inject({ method: "POST", url: "/api/scheduler/pause" });
    const body = res.json();
    expect(body.state).toMatchObject({
      dispatch_paused: true,
      running: false,
    });
    expect(typeof body.state.scheduler_status).toBe("string");
    expect(body.state).toHaveProperty("session_id");
    expect(typeof body.state._rev).toBe("number");
  });

  it("POST /api/scheduler/resume returns state with dispatch_paused=false", async () => {
    await app.inject({ method: "POST", url: "/api/scheduler/pause" });
    const res = await app.inject({ method: "POST", url: "/api/scheduler/resume" });
    expect(res.json().state).toMatchObject({
      dispatch_paused: false,
      running: false,
    });
  });

  it("POST /api/scheduler/start returns state.scheduler_status reflecting post-start state", async () => {
    const { app: wired, state } = await makeWiredServer(dir, {
      startScheduler: async () => {
        await state.update((s) => {
          s.running = true;
        });
        return { started: true, reason: "started" };
      },
    });
    try {
      const res = await wired.inject({ method: "POST", url: "/api/scheduler/start" });
      const body = res.json();
      expect(body.state).toMatchObject({
        running: true,
        dispatch_paused: false,
      });
      expect(typeof body.state.scheduler_status).toBe("string");
    } finally {
      await wired.close();
    }
  });

  it("POST /api/scheduler/stop returns state.scheduler_status='stopped'", async () => {
    const { app: wired, state } = await makeWiredServer(dir, {
      stopScheduler: async () => {
        await state.update((s) => {
          s.running = false;
        });
        return { stopped: true, reason: "stopped" };
      },
    });
    try {
      await state.update((s) => {
        s.running = true;
      });
      const res = await wired.inject({ method: "POST", url: "/api/scheduler/stop" });
      expect(res.json().state).toMatchObject({
        scheduler_status: "stopped",
        running: false,
      });
    } finally {
      await wired.close();
    }
  });
});

describe("BG-25: scheduler start/stop lifecycle", () => {
  it("POST /api/scheduler/start 503s when no startScheduler dep is wired", async () => {
    const res = await app.inject({ method: "POST", url: "/api/scheduler/start" });
    expect(res.statusCode).toBe(503);
    expect(res.json().error).toBe("scheduler_unavailable");
  });

  it("POST /api/scheduler/start invokes the dep and reports running:true after", async () => {
    const { app: wired, state } = await makeWiredServer(dir, {
      startScheduler: async () => {
        await state.update((s) => {
          s.running = true;
        });
        return { started: true, reason: "started" };
      },
      stopScheduler: async () => {
        await state.update((s) => {
          s.running = false;
        });
        return { stopped: true, reason: "stopped" };
      },
    });
    try {
      const start = await wired.inject({ method: "POST", url: "/api/scheduler/start" });
      expect(start.statusCode).toBe(200);
      expect(start.json()).toMatchObject({ ok: true, started: true, running: true });

      const idem = await wired.inject({ method: "POST", url: "/api/scheduler/start" });
      expect(idem.json()).toMatchObject({ started: false, reason: "already_running", running: true });

      const status = await wired.inject({ method: "GET", url: "/api/status" });
      expect(status.json().state.running).toBe(true);
      // BG-40: /api/status mirrors scheduler_status + wait_reason.
      expect(status.json().state.scheduler_status).toBeDefined();
      expect("wait_reason" in status.json().state).toBe(true);

      const stop = await wired.inject({ method: "POST", url: "/api/scheduler/stop" });
      expect(stop.json()).toMatchObject({ stopped: true, running: false });

      // BG-40: after /stop, scheduler_intent="stopped" → status="stopped".
      const after = await wired.inject({ method: "GET", url: "/api/scheduler" });
      expect(after.json().status).toBe("stopped");
      expect(after.json().wait_reason).toBeNull();
    } finally {
      await wired.close();
    }
  });

  // BG-40: a failed start must roll back scheduler_intent so /api/scheduler.status
  // doesn't wedge at "starting" forever.
  it("POST /api/scheduler/start reverts intent on failed start (e.g. aria2_unavailable)", async () => {
    const { app: wired } = await makeWiredServer(dir, {
      startScheduler: async () => ({ started: false, reason: "aria2_unavailable" }),
      stopScheduler: async () => ({ stopped: false, reason: "not_running" }),
    });
    try {
      const start = await wired.inject({ method: "POST", url: "/api/scheduler/start" });
      expect(start.json()).toMatchObject({ started: false, reason: "aria2_unavailable" });
      const sched = await wired.inject({ method: "GET", url: "/api/scheduler" });
      expect(sched.json().status).toBe("stopped");
    } finally {
      await wired.close();
    }
  });

  it("POST /api/scheduler/resume auto-starts the loop when running:false", async () => {
    let startCalls = 0;
    const { app: wired, state } = await makeWiredServer(dir, {
      startScheduler: async () => {
        startCalls += 1;
        await state.update((s) => {
          s.running = true;
        });
        return { started: true, reason: "started" };
      },
      stopScheduler: async () => ({ stopped: false, reason: "not_running" }),
    });
    try {
      const res = await wired.inject({ method: "POST", url: "/api/scheduler/resume" });
      expect(res.statusCode).toBe(200);
      expect(res.json()).toMatchObject({ ok: true, paused: false, started: true });
      expect(startCalls).toBe(1);
    } finally {
      await wired.close();
    }
  });

  it("POST /api/downloads auto-starts the scheduler loop when running:false and not paused", async () => {
    let startCalls = 0;
    const { app: wired, state } = await makeWiredServer(dir, {
      startScheduler: async () => {
        startCalls += 1;
        await state.update((s) => {
          s.running = true;
        });
        return { started: true, reason: "started" };
      },
      stopScheduler: async () => ({ stopped: false, reason: "not_running" }),
    });
    try {
      // running:false, paused:false → adding an item must kick the loop.
      const res = await wired.inject({
        method: "POST",
        url: "/api/downloads",
        payload: { items: [{ url: "http://example.com/a.iso" }] },
      });
      expect(res.statusCode).toBe(200);
      expect(startCalls).toBe(1);

      // running:true now — second add must NOT call startScheduler again.
      const res2 = await wired.inject({
        method: "POST",
        url: "/api/downloads",
        payload: { items: [{ url: "http://example.com/b.iso" }] },
      });
      expect(res2.statusCode).toBe(200);
      expect(startCalls).toBe(1);

      // Operator-paused: bring loop down + flip paused, then add must NOT auto-start.
      await state.update((s) => {
        s.running = false;
        s.paused = true;
      });
      const res3 = await wired.inject({
        method: "POST",
        url: "/api/downloads",
        payload: { items: [{ url: "http://example.com/c.iso" }] },
      });
      expect(res3.statusCode).toBe(200);
      expect(startCalls).toBe(1);
    } finally {
      await wired.close();
    }
  });

  it("GET /api/status exposes a top-level bandwidth summary lifted from state.last_bandwidth_probe", async () => {
    const env = { ARIAFLOW_DIR: dir };
    const lock = new StorageLock(storageLockPath(env));
    const state = new StateStore(lock, env);
    await state.update((s) => {
      s.last_bandwidth_probe = {
        source: "networkquality",
        reason: "ok",
        downlink_mbps: 100,
        cap_mbps: 80,
        cap_bytes_per_sec: 80 * 125_000,
        interface_name: "en0",
        interval_seconds: 180,
        down_cap_mbps: 80,
        up_cap_mbps: null,
      };
      s.last_bandwidth_probe_at = 1234.5;
    });
    const res = await app.inject({ method: "GET", url: "/api/status" });
    const body = res.json();
    expect(body.bandwidth).toMatchObject({
      source: "networkquality",
      interface_name: "en0",
      cap_mbps: 80,
      cap_bytes_per_sec: 80 * 125_000,
      downlink_mbps: 100,
      last_probe_at: 1234.5,
    });
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
  it("returns BG-20 contract: ariaflow-server / aria2 / networkquality", async () => {
    const res = await app.inject({ method: "GET", url: "/api/lifecycle" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.ok).toBe(true);

    // Hyphenated key — the dashboard reads data['ariaflow-server'].
    expect(body["ariaflow-server"].result).toMatchObject({
      reason: "match",
      outcome: "installed · current",
      observation: "ok",
      version: "0.0.0",
    });

    // aria2: no client wired in tests -> reason=missing.
    expect(body.aria2.result.reason).toMatch(/missing|stopped/);

    // networkquality: ready or missing depending on host (Linux runners
    // typically lack networkQuality), but the result shape is fixed.
    expect(body.networkquality.result).toHaveProperty("reason");
    expect(["ready", "missing"]).toContain(body.networkquality.result.reason);
    expect(body.networkquality.result).toHaveProperty("outcome");

    // BG-44 phase 3: standalone aria2-launchd row retired; auto-start
    // info now lives entirely on aria2.result.auto_start.
    expect(body["aria2-launchd"]).toBeUndefined();
    expect(body.aria2.result.auto_start).toMatchObject({
      installed: expect.any(Boolean),
    });
    expect(["launchd", "systemd", null]).toContain(
      body.aria2.result.auto_start.target,
    );

    expect(body.session_id).toBeNull();
    expect(body.session_closed_at).toBeNull();
  });

  it("BG-29: aria2 record carries expected_running + managed_by; idle queue → expected_running:false", async () => {
    const res = await app.inject({ method: "GET", url: "/api/lifecycle" });
    const body = res.json();
    // No items, no running scheduler → aria2 isn't expected to run.
    expect(body.aria2.result).toMatchObject({
      expected_running: false,
      managed_by: null, // not running in tests
    });
    // ariaflow-server / networkquality: opinion-free on
    // expected_running so the dashboard treats them as always-on.
    expect(body["ariaflow-server"].result.expected_running).toBeNull();
    expect(body.networkquality.result.expected_running).toBeNull();
  });

  it("BG-29: queued work flips aria2.expected_running to true", async () => {
    await app.inject({
      method: "POST",
      url: "/api/downloads",
      payload: { items: [{ url: "http://h/big.iso" }] },
    });
    const res = await app.inject({ method: "GET", url: "/api/lifecycle" });
    expect(res.json().aria2.result.expected_running).toBe(true);
  });

  it("BG-27: exposes installed/current/running axes on every component", async () => {
    const res = await app.inject({ method: "GET", url: "/api/lifecycle" });
    const body = res.json();

    // ariaflow-server: all three true; expected_version mirrors version.
    expect(body["ariaflow-server"].result).toMatchObject({
      installed: true,
      current: true,
      running: true,
      expected_version: "0.0.0",
    });

    // aria2: no RPC client wired → running=false. installed depends on
    // whether the host has aria2c on PATH; current is null when not
    // installed or when running is null.
    expect(body.aria2.result.running).toBe(false);
    expect(typeof body.aria2.result.installed).toBe("boolean");
    expect(body.aria2.result).toHaveProperty("current");

    // networkquality: current is always null (no version policy).
    expect(body.networkquality.result.current).toBeNull();
    expect(typeof body.networkquality.result.installed).toBe("boolean");
    // running is null (installed but no recent probe) or false (not installed).
    expect([null, true, false]).toContain(body.networkquality.result.running);
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

  it("option returns aria2.getOption keys spread at top level (BG-22)", async () => {
    const mock = await mockServerWithAria2(dir, () => ({ split: "5", "max-tries": "3" }));
    try {
      const res = await mock.inject({ method: "GET", url: "/api/aria2/option?gid=G1" });
      const body = res.json();
      // aria2 keys are spread at top level so the dashboard's
      // aria2Options[opt] lookups resolve.
      expect(body).toMatchObject({
        ok: true,
        gid: "G1",
        split: "5",
        "max-tries": "3",
      });
      // The legacy `options` wrapper must NOT be present.
      expect(body.options).toBeUndefined();
    } finally {
      await mock.close();
    }
  });

  it("global_option spreads keys at top level too (BG-22)", async () => {
    const mock = await mockServerWithAria2(dir, () => ({
      "connect-timeout": "60",
      "max-concurrent-downloads": "5",
    }));
    try {
      const res = await mock.inject({ method: "GET", url: "/api/aria2/global_option" });
      const body = res.json();
      expect(body).toMatchObject({
        ok: true,
        "connect-timeout": "60",
        "max-concurrent-downloads": "5",
      });
      expect(body.options).toBeUndefined();
    } finally {
      await mock.close();
    }
  });

  it("get_global_option (legacy alias) shares the same shape", async () => {
    const mock = await mockServerWithAria2(dir, () => ({ split: "16" }));
    try {
      const res = await mock.inject({ method: "GET", url: "/api/aria2/global_option" });
      const body = res.json();
      expect(body.split).toBe("16");
      expect(body.options).toBeUndefined();
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
  const { Aria2Client } = await import("@ariaflow/core");
  const client = new Aria2Client({ fetch: fetchImpl as unknown as typeof fetch });
  return (await makeWiredServer(baseDir, { aria2: client })).app;
}

describe("GET /api/openapi", () => {
  it("returns a generated OpenAPI 3.0+ doc covering the live routes", async () => {
    const res = await app.inject({ method: "GET", url: "/api/openapi" });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.openapi).toMatch(/^3\.0/);
    // Every registered route is in the doc.
    expect(body.paths["/api/downloads"]).toBeTruthy();
    expect(body.paths["/api/declaration"]).toBeTruthy();
    expect(body.paths["/api/openapi"]).toBeTruthy();
    // Per-route tags arrive incrementally as schemas land in routes/*.ts;
    // until then the doc is shape-correct but tag-light.
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
