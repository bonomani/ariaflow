import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  downloadSha256,
  renderFormula,
  tarballUrl,
  versionFromTag,
  writeFormula,
} from "./formula.js";

describe("versionFromTag", () => {
  it("strips the leading v from a stable tag", () => {
    expect(versionFromTag("v1.2.3")).toBe("1.2.3");
  });
  it("rejects pre-release / dev / blank tags", () => {
    expect(() => versionFromTag("1.2.3")).toThrow(/vX\.Y\.Z/);
    expect(() => versionFromTag("v1.2.3-rc1")).toThrow();
    expect(() => versionFromTag("")).toThrow();
  });
});

describe("tarballUrl", () => {
  it("returns the canonical GitHub release tarball url", () => {
    expect(tarballUrl("v0.1.190")).toBe(
      "https://github.com/bonomani/ariaflow-server/archive/refs/tags/v0.1.190.tar.gz",
    );
  });
});

describe("downloadSha256", () => {
  it("hashes a streamed response body", async () => {
    const body = new Uint8Array([0x68, 0x65, 0x6c, 0x6c, 0x6f]); // "hello"
    const fakeFetch = vi.fn(
      async () =>
        new Response(body, { status: 200, headers: { "content-type": "application/octet-stream" } }),
    );
    const hex = await downloadSha256("http://x/y", fakeFetch as unknown as typeof fetch);
    expect(hex).toBe("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
  });

  it("throws on a non-OK response", async () => {
    const fakeFetch = vi.fn(async () => new Response(null, { status: 404 }));
    await expect(downloadSha256("http://x", fakeFetch as unknown as typeof fetch)).rejects.toThrow(
      /failed to fetch/,
    );
  });
});

describe("renderFormula", () => {
  it("emits the TS-backed class with Node + aria2 deps and both bin shims", () => {
    const text = renderFormula({
      version: "1.2.3",
      url: "https://example/y.tar.gz",
      sha256: "deadbeef",
    });
    expect(text).toContain("class AriaflowServer < Formula");
    expect(text).toContain('depends_on "node"');
    expect(text).toContain('depends_on "aria2"');
    expect(text).toContain('depends_on "pnpm" => :build');
    expect(text).not.toContain('"corepack"');
    expect(text).toContain('url "https://example/y.tar.gz"');
    expect(text).toContain('sha256 "deadbeef"');
    expect(text).toContain('version "1.2.3"');
    // Canonical `ariaflow` plus back-compat `ariaflow-server` shim.
    expect(text).toContain('(bin/"ariaflow")');
    expect(text).toContain('(bin/"ariaflow-server")');
    expect(text).toContain("service do");
    expect(text).toContain("--scheduler");
    expect(text).toMatch(/keep_alive true/);
    // No Python residue.
    expect(text).not.toContain("portalocker");
    expect(text).not.toContain("python3");
  });
});

describe("writeFormula", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "ariaflow-formula-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("creates parent directories and writes utf8 content", async () => {
    const path = join(dir, "Formula", "ariaflow-server.rb");
    await writeFormula(path, "class X; end\n");
    expect(readFileSync(path, "utf8")).toBe("class X; end\n");
  });
});
