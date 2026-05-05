import { mkdtempSync, mkdirSync, writeFileSync, rmSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { findNetworkQuality, networkqualityStatus } from "./networkquality.js";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-install-"));
  mkdirSync(join(dir, "bin"));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("findNetworkQuality", () => {
  it("returns null when nothing is on PATH and no fallback is reachable", () => {
    expect(findNetworkQuality({ PATH: join(dir, "bin") }, [])).toBeNull();
  });

  it("returns the binary when present under either casing on PATH", () => {
    const path = join(dir, "bin", "networkQuality");
    writeFileSync(path, "#!/bin/sh\n");
    chmodSync(path, 0o755);
    expect(findNetworkQuality({ PATH: join(dir, "bin") }, [])).toBe(path);
  });
});

describe("networkqualityStatus", () => {
  it("reports missing when the tool is not on PATH", () => {
    const s = networkqualityStatus({ PATH: join(dir, "bin") }, []);
    expect(s).toMatchObject({
      installed: false,
      usable: false,
      reason: "missing",
      message: "networkquality tool not found",
    });
    expect(s.command).toBeUndefined();
  });

  it("reports ready and surfaces the resolved path when found", () => {
    // Match the casing of the first probe name in findNetworkQuality so
    // case-insensitive filesystems (macOS APFS default) return the path
    // with the same casing the caller asked for.
    const path = join(dir, "bin", "networkQuality");
    writeFileSync(path, "#!/bin/sh\n");
    chmodSync(path, 0o755);
    const s = networkqualityStatus({ PATH: join(dir, "bin") }, []);
    expect(s.installed).toBe(true);
    expect(s.usable).toBe(true);
    expect(s.reason).toBe("ready");
    expect(s.command).toBe(path);
    expect(s.message).toContain(path);
  });
});

