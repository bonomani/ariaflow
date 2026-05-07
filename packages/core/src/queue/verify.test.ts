import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { verifyExistingTier1 } from "./verify.js";

describe("verifyExistingTier1 (BG-55)", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "verify-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("returns null when downloadDir is empty", () => {
    expect(verifyExistingTier1("https://h/a.iso", "", null)).toBeNull();
  });

  it("returns null when no file exists at the URL basename under downloadDir", () => {
    expect(verifyExistingTier1("https://h/missing.iso", dir, null)).toBeNull();
  });

  it("returns absolute path when URL basename file exists", () => {
    const p = join(dir, "file.iso");
    writeFileSync(p, "x");
    expect(verifyExistingTier1("https://h/path/file.iso", dir, null)).toBe(p);
  });

  it("uses the trimmed bare-filename `output` over URL basename when provided", () => {
    const p = join(dir, "renamed.iso");
    writeFileSync(p, "x");
    expect(
      verifyExistingTier1("https://h/raw.iso", dir, "  renamed.iso  "),
    ).toBe(p);
  });

  it("ignores `output` when it contains a path component (not a bare filename)", () => {
    // `output` with a slash is supposed to come from the dispatcher's
    // dir resolution, not the verify gate. Falls back to URL basename.
    writeFileSync(join(dir, "fallback.iso"), "x");
    expect(
      verifyExistingTier1("https://h/fallback.iso", dir, "sub/dir/x.iso"),
    ).toBe(join(dir, "fallback.iso"));
  });

  it("returns null when the URL has no basename component", () => {
    expect(verifyExistingTier1("https://h/", dir, null)).toBeNull();
  });

  it("returns null when path resolves to a directory, not a file", () => {
    mkdirSync(join(dir, "subdir.iso"));
    expect(verifyExistingTier1("https://h/subdir.iso", dir, null)).toBeNull();
  });

  it("returns null on malformed URL", () => {
    expect(verifyExistingTier1("not a url", dir, null)).toBeNull();
  });
});
