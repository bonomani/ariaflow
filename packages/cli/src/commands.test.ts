import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { makeContext, type CliContext } from "./context.js";
import {
  cmdAdd,
  cmdBandwidth,
  cmdCleanup,
  cmdDashboard,
  cmdDeclaration,
  cmdList,
  cmdOpenapi,
  cmdPause,
  cmdProbe,
  cmdRemove,
  cmdResume,
  cmdInstallService,
  cmdSeedStop,
  cmdServe,
  cmdSetPref,
  cmdStatus,
  cmdWatch,
} from "./commands.js";

let dir: string;
let ctx: CliContext;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-cli-"));
  ctx = makeContext({ ARIAFLOW_DIR: dir });
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("cmdAdd", () => {
  it("returns JSON with id, url, status=queued, duplicate=false", async () => {
    const r = await cmdAdd(ctx, "http://h/x");
    expect(r.exitCode).toBe(0);
    const body = JSON.parse(r.stdout);
    expect(body.url).toBe("http://h/x");
    expect(body.status).toBe("queued");
    expect(body.duplicate).toBe(false);
  });

  it("flags duplicates on a second add of the same URL", async () => {
    await cmdAdd(ctx, "http://h/dup");
    const r2 = await cmdAdd(ctx, "http://h/dup");
    expect(JSON.parse(r2.stdout).duplicate).toBe(true);
  });

  it("--pretty prints a human summary instead of JSON", async () => {
    const r = await cmdAdd(ctx, "http://h/x", { pretty: true });
    expect(r.stdout).toMatch(/^added [0-9a-f-]{36}\n {2}url: http:\/\/h\/x\n {2}status: queued\n$/);
  });

  it("rejects an empty URL with exit 1", async () => {
    const r = await cmdAdd(ctx, "");
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toContain("url is required");
  });
});

describe("cmdList", () => {
  it("emits an empty summary when nothing is queued", async () => {
    const r = await cmdList(ctx);
    const body = JSON.parse(r.stdout);
    expect(body.summary.total).toBe(0);
    expect(body.items).toEqual([]);
  });

  it("--pretty mode prints '(no items)' on empty", async () => {
    const r = await cmdList(ctx, { pretty: true });
    expect(r.stdout).toBe("(no items)\n");
  });

  it("returns added items with their allowed actions", async () => {
    await cmdAdd(ctx, "http://h/a");
    await cmdAdd(ctx, "http://h/b");
    const r = await cmdList(ctx);
    const body = JSON.parse(r.stdout);
    expect(body.summary.total).toBe(2);
    expect(body.items[0].actions).toEqual(["pause", "remove"]);
  });
});

describe("cmdRemove", () => {
  it("removes an existing item", async () => {
    const add = await cmdAdd(ctx, "http://h/x");
    const id = JSON.parse(add.stdout).id;
    const r = await cmdRemove(ctx, id);
    expect(r.exitCode).toBe(0);
    expect(JSON.parse(r.stdout)).toEqual({ removed: id });
    const list = await cmdList(ctx);
    expect(JSON.parse(list.stdout).summary.total).toBe(0);
  });

  it("exit 2 on a missing id", async () => {
    const r = await cmdRemove(ctx, "00000000-0000-0000-0000-000000000000");
    expect(r.exitCode).toBe(2);
    expect(r.stdout).toContain("not found");
  });
});

describe("cmdStatus", () => {
  it("reports the default state with the queue summary", async () => {
    await cmdAdd(ctx, "http://h/x");
    const r = await cmdStatus(ctx);
    const body = JSON.parse(r.stdout);
    expect(body.session_id).toBeTruthy();
    expect(body.running).toBe(false);
    expect(body.summary.total).toBe(1);
    expect(body.summary.queued).toBe(1);
  });
});

describe("cmdPause / cmdResume", () => {
  it("pause flips status to paused with a paused_at stamp", async () => {
    const add = await cmdAdd(ctx, "http://h/x");
    const id = JSON.parse(add.stdout).id;
    const r = await cmdPause(ctx, id);
    const body = JSON.parse(r.stdout);
    expect(body.status).toBe("paused");
    expect(typeof body.paused_at).toBe("string");
  });

  it("resume flips status back to queued with a resumed_at stamp", async () => {
    const add = await cmdAdd(ctx, "http://h/x");
    const id = JSON.parse(add.stdout).id;
    await cmdPause(ctx, id);
    const r = await cmdResume(ctx, id);
    const body = JSON.parse(r.stdout);
    expect(body.status).toBe("queued");
    expect(typeof body.resumed_at).toBe("string");
  });

  it("exits 2 on a missing id for pause/resume", async () => {
    const fakeId = "00000000-0000-0000-0000-000000000000";
    expect((await cmdPause(ctx, fakeId)).exitCode).toBe(2);
    expect((await cmdResume(ctx, fakeId)).exitCode).toBe(2);
  });
});

describe("cmdBandwidth", () => {
  it("emits config derived from the declaration plus null probe by default", async () => {
    const r = await cmdBandwidth(ctx);
    const body = JSON.parse(r.stdout);
    expect(body.config.down_use_percent).toBeCloseTo(0.8, 5);
    expect(body.config.up_use_percent).toBeCloseTo(0.5, 5);
    expect(body.last_probe).toBeNull();
  });
});

describe("cmdDeclaration", () => {
  it("seeds and prints the default declaration on first call", async () => {
    const r = await cmdDeclaration(ctx);
    const body = JSON.parse(r.stdout);
    expect(body.meta.contract).toBe("UCC");
    expect(Array.isArray(body.uic.preferences)).toBe(true);
  });
});

describe("cmdWatch", () => {
  it("streams an action_logged event from a running server", async () => {
    const handle = await cmdServe(ctx, { host: "127.0.0.1", port: 0 });
    const lines: string[] = [];
    const out = { write: (s: string) => void lines.push(s) };
    const watch = cmdWatch({
      url: `${handle.url}/api/events`,
      out,
      // /api/events emits a "connected" handshake first, then cmdAdd
      // produces session_started + action_logged — wait for all three.
      limit: 3,
    });
    await new Promise((r) => setTimeout(r, 50));
    await cmdAdd(ctx, "http://h/x");
    await watch;
    await handle.close();
    const parsed = lines.map((l) => JSON.parse(l));
    const action = parsed.find((p: { event: string }) => p.event === "action_logged");
    expect(action).toBeDefined();
    expect(action.data.action).toBe("add");
  });

  it("returns a fail result when the URL is unreachable", async () => {
    const r = await cmdWatch({ url: "http://127.0.0.1:1/api/events", limit: 1 });
    expect(r.exitCode).toBe(1);
    expect(r.stdout).toContain("failed to connect");
  });
});

describe("cmdServe SSE", () => {
  it("echoes the request Origin on /api/events (CORS)", async () => {
    const handle = await cmdServe(ctx, { host: "127.0.0.1", port: 0, aria2Host: "" });
    try {
      const res = await fetch(`${handle.url}/api/events`, {
        headers: { Accept: "text/event-stream", Origin: "http://dashboard.local" },
      });
      expect(res.headers.get("access-control-allow-origin")).toBe("http://dashboard.local");
      await res.body?.cancel();
    } finally {
      await handle.close();
    }
  });

  it("emits a real named 'connected' event as the first frame", async () => {
    const handle = await cmdServe(ctx, { host: "127.0.0.1", port: 0, aria2Host: "" });
    try {
      const res = await fetch(`${handle.url}/api/events`, {
        headers: { Accept: "text/event-stream" },
      });
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const deadline = Date.now() + 1000;
      while (Date.now() < deadline) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        if (buffer.includes("\n\n")) break;
      }
      await reader.cancel();
      // First SSE frame must be a real named event ("event: connected"
      // followed by a data: line and a blank line) so EventSource clients
      // using addEventListener("connected", ...) actually fire.
      expect(buffer).toMatch(/event:\s*connected/);
      expect(buffer).toMatch(/data:\s*\{\}/);
      // And it must not be the SSE comment shape (": connected") which
      // browsers strip during parsing.
      expect(buffer.startsWith(":")).toBe(false);
    } finally {
      await handle.close();
    }
  });
});

describe("cmdServe", () => {
  it("boots a real HTTP server on a free port and answers /api/health", async () => {
    const handle = await cmdServe(ctx, { host: "127.0.0.1", port: 0, version: "9.9.9" });
    try {
      const res = await fetch(`${handle.url}/api/health`);
      expect(res.status).toBe(200);
      const body = (await res.json()) as { ok: boolean; status: string };
      expect(body.ok).toBe(true);
      expect(body.status).toBe("healthy");
      const v = await fetch(`${handle.url}/api/version`);
      const versionBody = (await v.json()) as { version: string };
      expect(versionBody.version).toBe("9.9.9");
    } finally {
      await handle.close();
    }
  });
});

describe("cmdOpenapi", () => {
  it("emits a 3.0.3 doc with the live routes tagged", async () => {
    const r = await cmdOpenapi(ctx);
    expect(r.exitCode).toBe(0);
    const doc = JSON.parse(r.stdout);
    expect(doc.openapi).toBe("3.0.3");
    expect(doc.paths["/api/downloads"]).toBeTruthy();
    expect(doc.paths["/api/downloads"].post.tags).toEqual(["Queue"]);
  });
});

describe("cmdCleanup", () => {
  const writeStaleItem = async () => {
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
  };

  it("--dry-run reports the split without persisting", async () => {
    await writeStaleItem();
    const r = await cmdCleanup(ctx, { dryRun: true });
    expect(JSON.parse(r.stdout)).toEqual({ archived: 1, remaining: 1, dry_run: true });
    const items = await ctx.queue.load();
    expect(items).toHaveLength(2); // unchanged
  });

  it("real run archives stale terminals and shrinks the queue", async () => {
    await writeStaleItem();
    const r = await cmdCleanup(ctx);
    expect(JSON.parse(r.stdout)).toEqual({ archived: 1, remaining: 1, dry_run: false });
    expect(await ctx.queue.load()).toHaveLength(1);
    const archived = await ctx.archive.load();
    expect(archived).toHaveLength(1);
    expect(archived[0]!.id).toBe("11111111-1111-1111-1111-111111111111");
  });
});

describe("cmdDashboard", () => {
  it("JSON mode emits scheduler / queue / bandwidth / declaration sections", async () => {
    await cmdAdd(ctx, "http://h/x");
    const r = await cmdDashboard(ctx);
    const body = JSON.parse(r.stdout);
    expect(body.scheduler.status).toBe("starting");
    expect(body.queue.total).toBe(1);
    expect(body.queue.queued).toBe(1);
    expect(body.bandwidth.config.probe_interval_seconds).toBeGreaterThanOrEqual(30);
    expect(body.declaration.contract).toBe("UCC");
    expect(body.declaration.gates).toBe(2);
  });

  it("--pretty emits a human layout including the no-probe hint", async () => {
    const r = await cmdDashboard(ctx, { pretty: true });
    expect(r.stdout).toContain("Scheduler: starting");
    expect(r.stdout).toContain("Queue: total=0");
    expect(r.stdout).toContain("Bandwidth: no probe yet");
    expect(r.stdout).toContain("Declaration: UCC v2.0");
  });

  it("--pretty surfaces a saved probe's downlink / cap", async () => {
    await cmdProbe(ctx);
    const r = await cmdDashboard(ctx, { pretty: true });
    expect(r.stdout).toMatch(/Bandwidth: downlink=/);
  });
});

describe("cmdProbe", () => {
  it("returns the default-source probe and persists it on state", async () => {
    const r = await cmdProbe(ctx);
    expect(r.exitCode).toBe(0);
    const body = JSON.parse(r.stdout);
    expect(body.probe.source).toBe("default");
    expect(body.config.probe_interval_seconds).toBeGreaterThanOrEqual(30);
    const state = await ctx.state.load();
    expect(state.last_bandwidth_probe).toBeTruthy();
    expect(typeof state.last_bandwidth_probe_at).toBe("number");
  });
});

describe("cmdSetPref", () => {
  it("coerces numeric/boolean strings and persists the value", async () => {
    const r = await cmdSetPref(ctx, "max_simultaneous_downloads", "3");
    expect(r.exitCode).toBe(0);
    expect(JSON.parse(r.stdout)).toEqual({
      name: "max_simultaneous_downloads",
      before: 1,
      after: 3,
    });
    const r2 = await cmdSetPref(ctx, "auto_preflight_on_run", "true");
    expect(JSON.parse(r2.stdout).after).toBe(true);
  });

  it("exit 2 on an unknown preference", async () => {
    const r = await cmdSetPref(ctx, "no_such_pref", "1");
    expect(r.exitCode).toBe(2);
  });
});

describe("cmdInstallService (dry-run)", () => {
  it("prints the install plan without spawning when --dry-run is set", async () => {
    const r = await cmdInstallService({ dryRun: true, binPath: "aria2c" });
    if (r.exitCode === 0) {
      const body = JSON.parse(r.stdout);
      expect(body.target).toMatch(/^aria2-(launchd|systemd)$/);
      expect(Array.isArray(body.commands)).toBe(true);
      expect(body.commands.length).toBeGreaterThan(0);
    } else {
      // Unsupported platform — surface the canonical error string.
      expect(r.stdout).toMatch(/not supported/);
    }
  });
});

describe("cmdSeedStop", () => {
  it("exit 2 when no active seed matches", async () => {
    const r = await cmdSeedStop(ctx, "nope");
    expect(r.exitCode).toBe(2);
  });

  it("flips distribute_status to stopped", async () => {
    const { writeFileSync } = await import("node:fs");
    writeFileSync(
      `${dir}/queue.json`,
      JSON.stringify({
        items: [
          {
            id: "11111111-1111-1111-1111-111111111111",
            url: "http://h/x",
            distribute_status: "seeding",
            distribute_infohash: "abc",
          },
        ],
      }),
    );
    const r = await cmdSeedStop(ctx, "abc");
    expect(r.exitCode).toBe(0);
    expect(JSON.parse(r.stdout)).toEqual({ infohash: "abc", status: "stopped" });
  });
});
