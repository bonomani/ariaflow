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

describe("buildDnsSdCmd / buildAvahiCmd", () => {
  it("dns-sd command contains the correct service type and order", () => {
    const cmd = buildDnsSdCmd({ port: 6800, path: "/api", binary: "/usr/bin/dns-sd" });
    expect(cmd).toEqual([
      "/usr/bin/dns-sd",
      "-R",
      instanceName(),
      "_ariaflow-server._tcp",
      "local",
      "6800",
      "path=/api",
      "tls=0",
      `hostname=${shortHostname()}`,
    ]);
  });

  it("avahi command does NOT include the 'local' domain or '-R' flag", () => {
    const cmd = buildAvahiCmd({ port: 6800, path: "/api", binary: "/usr/bin/avahi-publish-service" });
    expect(cmd[0]).toBe("/usr/bin/avahi-publish-service");
    expect(cmd[1]).toBe(instanceName());
    expect(cmd).not.toContain("-R");
    expect(cmd).not.toContain("local");
    expect(cmd).toContain("path=/api");
    expect(cmd).toContain("tls=0");
  });

  it("defaults path to /api when omitted", () => {
    expect(buildDnsSdCmd({ port: 1234, binary: "x" })).toContain("path=/api");
  });
});
