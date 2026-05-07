import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { resolvePkgManager } from "./pkg_manager.js";

describe("resolvePkgManager (BG-60)", () => {
  let dir: string;
  const origPath = process.env.PATH;
  const origHome = process.env.HOME;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "pkg-mgr-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
    if (origPath === undefined) delete process.env.PATH;
    else process.env.PATH = origPath;
    if (origHome === undefined) delete process.env.HOME;
    else process.env.HOME = origHome;
  });

  it("returns the absolute path when the binary is on $PATH", () => {
    const exe = join(dir, "fake-pkg");
    writeFileSync(exe, "#!/bin/sh\nexit 0\n");
    chmodSync(exe, 0o755);
    process.env.PATH = `${dir}${delimiter}/usr/bin`;
    expect(resolvePkgManager("fake-pkg")).toBe(exe);
  });

  it("falls through to the bare name when neither PATH nor known prefixes match", () => {
    process.env.PATH = "/nonexistent-9876";
    process.env.HOME = "/nonexistent-home-9876";
    expect(resolvePkgManager("definitely-not-a-real-binary")).toBe(
      "definitely-not-a-real-binary",
    );
  });

  it("skips empty PATH segments without crashing", () => {
    process.env.PATH = `${delimiter}${delimiter}/usr/bin`;
    // Just exercising the branch — return value isn't important; the
    // assertion is "no throw".
    expect(() => resolvePkgManager("anything")).not.toThrow();
  });
});
