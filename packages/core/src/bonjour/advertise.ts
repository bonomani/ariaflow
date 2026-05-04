import { spawn as nodeSpawn, type ChildProcess } from "node:child_process";
import {
  buildAvahiCmd,
  buildDnsSdCmd,
  detectBackend,
  type BonjourBackend,
} from "./bonjour.js";

export interface AdvertiseHandle {
  backend: BonjourBackend | null;
  /** Stop the advertisement (SIGTERM, then SIGKILL after 1s). */
  stop: () => Promise<void>;
}

export interface AdvertiseOptions {
  port: number;
  path?: string;
  /** Override the auto-detected backend (testing). */
  backend?: BonjourBackend;
  /** Spawn override (testing). */
  spawn?: typeof nodeSpawn;
  /** Optional logger; defaults to console. */
  logger?: { warn(...args: unknown[]): void };
}

/**
 * Advertise the running ariaflow-server over mDNS as
 * `_ariaflow-server._tcp` so dashboards on the same L2 segment can
 * discover it without configuration.
 *
 * Backend selection:
 *   - macOS / Windows / WSL: `dns-sd -R ...`
 *   - Linux: `avahi-publish-service ...`
 *   - Unsupported / no backend on PATH: returns a no-op handle.
 *
 * The child stays alive until stop() is called; on shutdown we send
 * SIGTERM and follow up with SIGKILL after 1s if the process hasn't
 * exited. RPC failures (binary not found, daemon down) are surfaced via
 * the optional logger but never throw — the server should keep serving
 * HTTP even if mDNS is unavailable.
 */
export function advertiseHttpService(opts: AdvertiseOptions): AdvertiseHandle {
  const backend = opts.backend ?? detectBackend();
  const log = opts.logger ?? { warn: (...args: unknown[]) => console.warn(...args) };
  if (!backend) {
    return { backend: null, stop: async () => {} };
  }
  const path = opts.path ?? "/api";
  const argv =
    backend === "dns-sd"
      ? buildDnsSdCmd({ port: opts.port, path })
      : buildAvahiCmd({ port: opts.port, path });
  let proc: ChildProcess | null = null;
  try {
    proc = (opts.spawn ?? nodeSpawn)(argv[0]!, argv.slice(1), {
      stdio: ["ignore", "ignore", "pipe"],
      detached: false,
    });
    proc.on("error", (err) => {
      log.warn(`mDNS announce (${backend}) failed:`, err.message);
    });
    proc.on("exit", (code, signal) => {
      if (code !== 0 && code !== null && signal === null) {
        log.warn(`mDNS announce (${backend}) exited code=${code}`);
      }
    });
  } catch (err) {
    log.warn(`mDNS announce (${backend}) spawn error:`, (err as Error).message);
    return { backend, stop: async () => {} };
  }
  return {
    backend,
    stop: () =>
      new Promise<void>((resolve) => {
        if (!proc || proc.exitCode !== null) return resolve();
        const finish = () => resolve();
        proc.once("exit", finish);
        proc.kill("SIGTERM");
        const killTimer = setTimeout(() => {
          if (proc && proc.exitCode === null) proc.kill("SIGKILL");
        }, 1000);
        // Don't keep the event loop alive just for the kill timer.
        killTimer.unref?.();
      }),
  };
}
