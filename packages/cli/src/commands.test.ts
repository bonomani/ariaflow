import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { makeContext, type CliContext } from "./context.js";
import {
  cmdAdd,
  cmdBandwidth,
  cmdDeclaration,
  cmdList,
  cmdPause,
  cmdRemove,
  cmdResume,
  cmdStatus,
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
