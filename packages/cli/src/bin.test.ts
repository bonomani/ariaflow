import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const cliPkg = resolve(here, "..");
const bin = join(cliPkg, "dist", "index.js");

let dir: string;

beforeAll(() => {
  if (!existsSync(bin)) {
    throw new Error(
      `CLI bin not built: ${bin}. Run 'pnpm build' before this test suite.`,
    );
  }
});

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-cli-bin-"));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const run = (args: string[]) =>
  spawnSync("node", [bin, ...args], {
    env: { ...process.env, ARIAFLOW_DIR: dir },
    encoding: "utf8",
  });

describe("ariaflow CLI bin", () => {
  it("--version prints something", () => {
    const r = run(["--version"]);
    expect(r.status).toBe(0);
    expect(r.stdout.trim()).toMatch(/.+/);
  });

  it("add → list → remove round-trip", () => {
    const add = run(["add", "http://h/x"]);
    expect(add.status).toBe(0);
    const id = JSON.parse(add.stdout).id;

    const list = run(["list"]);
    const body = JSON.parse(list.stdout);
    expect(body.summary.total).toBe(1);
    expect(body.items[0].id).toBe(id);

    const rm = run(["remove", id]);
    expect(rm.status).toBe(0);
    expect(JSON.parse(rm.stdout)).toEqual({ removed: id });

    const list2 = run(["list"]);
    expect(JSON.parse(list2.stdout).summary.total).toBe(0);
  });

  it("status reports queue summary", () => {
    run(["add", "http://h/a"]);
    run(["add", "http://h/b"]);
    const r = run(["status"]);
    expect(r.status).toBe(0);
    const body = JSON.parse(r.stdout);
    expect(body.summary.total).toBe(2);
    expect(body.summary.queued).toBe(2);
    expect(body.session_id).toBeTruthy();
  });

  it("--pretty emits human-readable add output", () => {
    const r = run(["add", "http://h/x", "--pretty"]);
    expect(r.status).toBe(0);
    expect(r.stdout).toMatch(/^added [0-9a-f-]{36}\n/);
  });

  it("exits 2 when removing an unknown id", () => {
    const r = run(["remove", "00000000-0000-0000-0000-000000000000"]);
    expect(r.status).toBe(2);
    expect(r.stdout).toContain("not found");
  });
});
