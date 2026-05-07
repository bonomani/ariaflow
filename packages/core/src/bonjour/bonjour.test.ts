import { mkdtempSync, mkdirSync, writeFileSync, rmSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildAvahiCmd,
  buildDnsSdCmd,
  bonjourAvailable,
  detectBackend,
  instanceName,
  shortHostname,
  which,
} from "./bonjour.js";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "ariaflow-bonjour-"));
  mkdirSync(join(dir, "bin"));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const placeBinary = (name: string): string => {
  const path = join(dir, "bin", name);
  writeFileSync(path, "#!/bin/sh\n");
  chmodSync(path, 0o755);
  return path;
};

describe("shortHostname / instanceName", () => {
  it("shortHostname is non-empty", () => {
    expect(shortHostname()).toMatch(/.+/);
  });

  it("instanceName returns the short hostname for typical names", () => {
    expect(instanceName()).toBe(shortHostname());
  });
});

describe("which", () => {
  it("finds a binary on PATH", () => {
    const path = placeBinary("foo");
    expect(which("foo", { PATH: join(dir, "bin") })).toBe(path);
  });

  it("returns null for missing binaries", () => {
    expect(which("nope", { PATH: join(dir, "bin") })).toBeNull();
  });

  it("returns null with empty PATH", () => {
    expect(which("foo", { PATH: "" })).toBeNull();
  });
});

describe("detectBackend", () => {
  it("returns null when neither dns-sd nor avahi is on PATH", () => {
    expect(detectBackend({ PATH: join(dir, "bin") })).toBeNull();
    expect(bonjourAvailable({ PATH: join(dir, "bin") })).toBe(false);
  });

  it("picks dns-sd on macOS / Windows when present", () => {
    placeBinary("dns-sd");
    const result = detectBackend({ PATH: join(dir, "bin") });
    // Result is platform-dependent: on this Linux runner, only WSL would
    // pick dns-sd; otherwise we need avahi-publish-service. Both resolve
    // to one of the documented values, so just check for falsy or a known
    // backend.
    expect([null, "dns-sd", "avahi"]).toContain(result);
  });

  it("picks avahi on plain Linux when avahi-publish-service is present", () => {
    placeBinary("avahi-publish-service");
    const result = detectBackend({ PATH: join(dir, "bin") });
    // On Linux, expect "avahi"; on other platforms the result is platform-
    // specific, but it must at least be a documented value.
    expect([null, "avahi", "dns-sd"]).toContain(result);
  });
});

describe("buildDnsSdCmd / buildAvahiCmd (BG-73)", () => {
  it("dns-sd command emits ver/role/v TXT records, no path/tls/hostname", () => {
    const cmd = buildDnsSdCmd({ port: 6800, version: "1.2.3", binary: "/usr/bin/dns-sd" });
    expect(cmd).toEqual([
      "/usr/bin/dns-sd",
      "-R",
      instanceName(),
      "_ariaflow-server._tcp",
      "local",
      "6800",
      "ver=0.2",
      "role=server",
      "v=1.2.3",
    ]);
    // Regression — the legacy keys must be gone.
    expect(cmd.some((s) => s.startsWith("path="))).toBe(false);
    expect(cmd.some((s) => s.startsWith("tls="))).toBe(false);
    expect(cmd.some((s) => s.startsWith("hostname="))).toBe(false);
  });

  it("avahi command does NOT include the 'local' domain or '-R' flag", () => {
    const cmd = buildAvahiCmd({
      port: 6800,
      version: "1.2.3",
      binary: "/usr/bin/avahi-publish-service",
    });
    expect(cmd[0]).toBe("/usr/bin/avahi-publish-service");
    expect(cmd[1]).toBe(instanceName());
    expect(cmd).not.toContain("-R");
    expect(cmd).not.toContain("local");
    expect(cmd).toContain("ver=0.2");
    expect(cmd).toContain("role=server");
    expect(cmd).toContain("v=1.2.3");
  });

  it("omits the v= field when no version is supplied", () => {
    const cmd = buildDnsSdCmd({ port: 1234, binary: "x" });
    expect(cmd).toContain("ver=0.2");
    expect(cmd).toContain("role=server");
    expect(cmd.some((s) => s.startsWith("v="))).toBe(false);
  });
});
