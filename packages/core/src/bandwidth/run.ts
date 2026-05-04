import { spawn as nodeSpawn } from "node:child_process";
import { findNetworkQuality } from "../install/networkquality.js";
import {
  applyFreeBandwidthCap,
  BYTES_PER_MEGABIT,
} from "./units.js";
import {
  defaultBandwidthProbe,
  parseNetworkQualityOutput,
  type BandwidthProbe,
} from "./probe.js";
import type { BandwidthConfig } from "./config.js";

interface RunProbeOptions {
  config: BandwidthConfig;
  /** Override networkQuality binary path; default = findNetworkQuality(). */
  binary?: string;
  /** Process spawn override (tests). */
  spawn?: typeof nodeSpawn;
  timeoutMs?: number;
}

export type ResolvedProbe = BandwidthProbe & {
  interval_seconds: number;
  down_cap_mbps: number | null;
  up_cap_mbps: number | null;
  cap_mbps?: number;
  cap_bytes_per_sec?: number;
};

/**
 * End-to-end bandwidth probe: spawn networkQuality (or fall back to a
 * default-source probe), apply the free-bandwidth cap from `config`,
 * and stamp interval_seconds + cap fields onto the result.
 *
 * Pure of storage / RPC concerns — the caller decides whether to
 * persist the result and push aria2 limits.
 */
export async function runBandwidthProbe(opts: RunProbeOptions): Promise<ResolvedProbe> {
  const spawn = opts.spawn ?? nodeSpawn;
  const timeoutMs = opts.timeoutMs ?? 10_000;
  // Escape hatch for tests / CI hosts where the real macOS networkQuality
  // binary exists but we don't want to spawn it (10 s+ wall clock).
  const disabled = process.env.ARIAFLOW_DISABLE_NETWORKQUALITY === "1";
  const cmd = opts.binary ?? (disabled ? null : findNetworkQuality());
  let probe: BandwidthProbe;
  if (!cmd) {
    probe = defaultBandwidthProbe({ floorMbps: 1, reason: "probe_unavailable" });
  } else {
    const argv = [cmd, "-u", "-c", "-s", "-M", "8"];
    const command = argv.join(" ");
    try {
      const stdout = await runProcess(spawn, argv, timeoutMs);
      const parsed = parseNetworkQualityOutput(stdout, {
        percent: opts.config.down_use_percent,
        floorMbps: 1,
      });
      if (parsed) {
        probe = parsed;
        probe.command = command;
      } else {
        probe = defaultBandwidthProbe({ floorMbps: 1, reason: "probe_no_parse", command });
      }
    } catch (err) {
      const reason =
        err instanceof Error && err.message === "timeout"
          ? "probe_timeout_no_parse"
          : "probe_error";
      probe = defaultBandwidthProbe({
        floorMbps: 1,
        reason,
        partial: reason === "probe_timeout_no_parse",
        command,
      });
    }
  }

  const downCap = applyFreeBandwidthCap(
    probe.downlink_mbps,
    opts.config.down_free_percent,
    opts.config.down_free_absolute_mbps,
  );
  const upCap = applyFreeBandwidthCap(
    probe.uplink_mbps ?? null,
    opts.config.up_free_percent,
    opts.config.up_free_absolute_mbps,
  );
  const out: ResolvedProbe = {
    ...probe,
    interval_seconds: opts.config.probe_interval_seconds,
    down_cap_mbps: downCap,
    up_cap_mbps: upCap,
  };
  if (downCap !== null) {
    out.cap_mbps = downCap;
    out.cap_bytes_per_sec = Math.max(1, Math.trunc(downCap * BYTES_PER_MEGABIT));
  }
  return out;
}

function runProcess(
  spawn: typeof nodeSpawn,
  argv: string[],
  timeoutMs: number,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn(argv[0]!, argv.slice(1), { stdio: ["ignore", "pipe", "ignore"] });
    const chunks: Buffer[] = [];
    proc.stdout?.on("data", (chunk: Buffer) => chunks.push(chunk));
    let settled = false;
    const timer = setTimeout(() => {
      settled = true;
      proc.kill("SIGTERM");
      setTimeout(() => proc.kill("SIGKILL"), 1000).unref();
      reject(new Error("timeout"));
    }, timeoutMs);
    timer.unref();
    proc.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(err);
    });
    proc.on("close", () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(Buffer.concat(chunks).toString("utf8"));
    });
  });
}
