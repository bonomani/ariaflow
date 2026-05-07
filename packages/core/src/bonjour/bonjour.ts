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
 * (RFC 6763).
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
 * Pick the available mDNS backend for the current platform: dns-sd on
 * macOS / Windows, avahi (or dns-sd via WSL interop) on Linux.
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
 * BG-73: TXT-record protocol version. Bumped when the field set changes
 * incompatibly. Consumers gate compat checks at pairing on this.
 */
export const MDNS_PROTOCOL_VERSION = "0.2";

interface BuildCmdOpts {
  port: number;
  /** Software version (from package.json); rendered as `v=...`. */
  version?: string;
  /** Override the dns-sd / avahi binary path (testing). */
  binary?: string;
}

/**
 * BG-73: TXT records published over `_ariaflow-server._tcp`.
 * `path` / `tls` / `hostname` were dropped — `path=/api` and `tls=0`
 * were constants every consumer hardcoded; `hostname` duplicated the
 * SRV target.
 *
 * `ver=<protocol>` and `role=server` are stable; `v=<software>` only
 * fires when the caller supplies it (cmdServe injects the resolved
 * package version).
 */
function txtRecords(version: string | undefined): string[] {
  const txt = [`ver=${MDNS_PROTOCOL_VERSION}`, "role=server"];
  if (version) txt.push(`v=${version}`);
  return txt;
}

/**
 * Build the dns-sd command (macOS / Windows) for advertising an HTTP
 * service named after the short hostname under _ariaflow-server._tcp.
 */
export function buildDnsSdCmd(opts: BuildCmdOpts): string[] {
  return [
    opts.binary ?? dnsSdPath() ?? "dns-sd",
    "-R",
    instanceName(),
    "_ariaflow-server._tcp",
    "local",
    String(opts.port),
    ...txtRecords(opts.version),
  ];
}

/**
 * Build the avahi-publish-service command (Linux, non-WSL).
 */
export function buildAvahiCmd(opts: BuildCmdOpts): string[] {
  return [
    opts.binary ?? avahiPublishPath() ?? "avahi-publish-service",
    instanceName(),
    "_ariaflow-server._tcp",
    String(opts.port),
    ...txtRecords(opts.version),
  ];
}
