import { existsSync } from "node:fs";
import { hostname, platform as osPlatform } from "node:os";
import { delimiter, join } from "node:path";
import { isLinux, isMacOS, isWindows, isWSL } from "../platform/detect.js";

export type BonjourBackend = "dns-sd" | "avahi";

export interface BonjourEnvironment {
  PATH?: string;
  PATHEXT?: string;
}

const DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD";

/** First label of the host's name (the "short" hostname). */
export function shortHostname(): string {
  return (hostname() || "unknown").split(".")[0]!;
}

/**
 * Bonjour instance name: the short hostname truncated to <=63 bytes UTF-8
 * (RFC 6763). Mirrors bonjour._instance_name.
 */
export function instanceName(): string {
  const name = shortHostname();
  const enc = new TextEncoder();
  const bytes = enc.encode(name);
  if (bytes.length <= 63) return name;
  // Drop bytes from the end until valid UTF-8 boundary, then decode.
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes.subarray(0, 63));
}

/**
 * Resolve a binary in PATH (cross-platform). Returns the absolute path
 * or null. On Windows / WSL also probes PATHEXT extensions.
 */
export function which(
  binary: string,
  env: BonjourEnvironment = process.env,
): string | null {
  const path = env.PATH ?? "";
  if (!path) return null;
  const pathExt = isWindows()
    ? (env.PATHEXT ?? DEFAULT_PATHEXT).split(";").map((e) => e.trim()).filter(Boolean)
    : [""];
  for (const dir of path.split(delimiter)) {
    if (!dir) continue;
    for (const ext of [""].concat(pathExt.filter((e) => e !== ""))) {
      const candidate = join(dir, binary + ext);
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
}

const dnsSdPath = (env?: BonjourEnvironment): string | null =>
  which("dns-sd", env) ?? which("dns-sd.exe", env);

const avahiPublishPath = (env?: BonjourEnvironment): string | null =>
  which("avahi-publish-service", env);

/**
 * Pick the available mDNS backend for the current platform. Mirrors
 * bonjour._detect_backend: dns-sd on macOS / Windows, avahi (or dns-sd
 * via WSL interop) on Linux.
 */
export function detectBackend(env: BonjourEnvironment = process.env): BonjourBackend | null {
  if (isMacOS() && dnsSdPath(env)) return "dns-sd";
  if (isWindows() && dnsSdPath(env)) return "dns-sd";
  if (isLinux()) {
    if (isWSL() && dnsSdPath(env)) return "dns-sd";
    if (avahiPublishPath(env)) return "avahi";
  }
  // Fallback for unknown platforms — useful only in tests.
  if (osPlatform() !== "darwin" && osPlatform() !== "win32" && osPlatform() !== "linux") {
    if (dnsSdPath(env)) return "dns-sd";
    if (avahiPublishPath(env)) return "avahi";
  }
  return null;
}

export const bonjourAvailable = (env?: BonjourEnvironment): boolean =>
  detectBackend(env) !== null;

/**
 * Build the dns-sd command (macOS / Windows) for advertising an HTTP
 * service named after the short hostname under _ariaflow-server._tcp.
 */
export function buildDnsSdCmd(opts: {
  port: number;
  path?: string;
  binary?: string;
}): string[] {
  const path = opts.path ?? "/api";
  return [
    opts.binary ?? dnsSdPath() ?? "dns-sd",
    "-R",
    instanceName(),
    "_ariaflow-server._tcp",
    "local",
    String(opts.port),
    `path=${path}`,
    "tls=0",
    `hostname=${shortHostname()}`,
  ];
}

/**
 * Build the avahi-publish-service command (Linux, non-WSL).
 */
export function buildAvahiCmd(opts: {
  port: number;
  path?: string;
  binary?: string;
}): string[] {
  const path = opts.path ?? "/api";
  return [
    opts.binary ?? avahiPublishPath() ?? "avahi-publish-service",
    instanceName(),
    "_ariaflow-server._tcp",
    String(opts.port),
    `path=${path}`,
    "tls=0",
    `hostname=${shortHostname()}`,
  ];
}
