import { existsSync } from "node:fs";
import { homedir } from "node:os";
import {
  detectAriaflowInstalledVia,
  detectAriaflowManagedBy,
  detectBinaryInstalledVia,
  findAria2c,
  install as installNs,
  type Aria2Client,
  type QueueItemRecord,
  type ServerState,
} from "@ariaflow/core";
import type { ServerDeps } from "../server.js";

const PENDING = new Set(["queued", "waiting", "active"]);
export const LAUNCHD_PLIST = `${homedir()}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`;
export const SYSTEMD_UNIT = `${homedir()}/.config/systemd/user/ariaflow-server-aria2.service`;

export interface ComponentRow {
  result: Record<string, unknown>;
}

interface AutoStart {
  installed: boolean;
  target: "launchd" | "systemd" | null;
  path: string | null;
}

/**
 * BG-44: surface aria2's auto-start mechanism on the aria2 row itself
 * (`auto_start` sub-object). Phase 3 retired the standalone
 * `aria2-launchd` row; FE migrated to reading this in v0.1.466.
 *
 * `target` is platform-detected (no auto-start mechanism on
 * Windows / unknown → null). `installed` checks for the actual file.
 */
function detectAria2AutoStart(): AutoStart {
  if (existsSync(LAUNCHD_PLIST)) {
    return { installed: true, target: "launchd", path: LAUNCHD_PLIST };
  }
  if (existsSync(SYSTEMD_UNIT)) {
    return { installed: true, target: "systemd", path: SYSTEMD_UNIT };
  }
  // Per the platform we know how to install onto: report the prospective
  // path as `path` (so the FE can display "would install to ...") with
  // installed=false.
  if (process.platform === "darwin") {
    return { installed: false, target: "launchd", path: LAUNCHD_PLIST };
  }
  if (process.platform === "linux") {
    return { installed: false, target: "systemd", path: SYSTEMD_UNIT };
  }
  return { installed: false, target: null, path: null };
}

/**
 * BG-20 + BG-27 + BG-29 + BG-43: ariaflow-server itself. We're
 * answering the request, so the three install/current/running axes
 * are all true and the version IS the expected version.
 *
 * BG-43 adds two orthogonal axes the dashboard reads to decide
 * whether to show Restart / Update buttons:
 *   managed_by    — who supervises this process (launchd, systemd,
 *                   docker, external, null) — drives Restart
 *   installed_via — where the binary came from (homebrew, pipx,
 *                   npm, source, null) — drives Update
 * Both auto-detected at request time from process state +
 * filesystem signals (see core/install/ariaflow_self.ts).
 */
export function buildAriaflowServerRow(deps: ServerDeps): ComponentRow {
  const expectedVersion = deps.version ?? "0.0.0";
  return {
    result: {
      installed: true,
      current: true,
      running: true,
      expected_running: null,
      managed_by: detectAriaflowManagedBy(),
      installed_via: detectAriaflowInstalledVia(),
      reason: "match",
      outcome: "installed · current",
      message: null,
      observation: "ok",
      completion: null,
      version: expectedVersion,
      expected_version: expectedVersion,
    },
  };
}

interface Aria2Probe {
  binPath: string | null;
  installed: boolean;
  running: boolean;
  version: string | null;
  err: string | null;
}

export async function probeAria2(client: Aria2Client | undefined): Promise<Aria2Probe> {
  const binPath = findAria2c();
  let running = false;
  let version: string | null = null;
  let err: string | null = null;
  if (client) {
    try {
      const v = await client.call<{ version: string }>("aria2.getVersion");
      running = true;
      version = v.version;
    } catch (e) {
      err = e instanceof Error ? e.message : String(e);
    }
  }
  return { binPath, installed: Boolean(binPath), running, version, err };
}

/**
 * BG-20 + BG-27 + BG-29: aria2 row. Splits "binary on disk" (installed)
 * from "RPC reachable" (running). expected_running mirrors the
 * scheduler's wish; managed_by is "launchd" iff our launchd plist is
 * present, else "external".
 */
export function buildAria2Row(
  probe: Aria2Probe,
  state: ServerState,
  items: QueueItemRecord[],
): ComponentRow {
  const current = probe.installed ? (probe.running ? true : null) : null;
  const workPending = items.some((i) => PENDING.has(String(i.status ?? "")));
  const expectedRunning =
    Boolean(state.running) || Boolean(state.active_gid) || workPending;
  const managedBy: "ariaflow" | "launchd" | "external" | null = probe.running
    ? existsSync(LAUNCHD_PLIST)
      ? "launchd"
      : "external"
    : null;
  return {
    result: {
      installed: probe.installed,
      current,
      running: probe.running,
      expected_running: expectedRunning,
      managed_by: managedBy,
      // BG-46: same axis we surface for ariaflow-server. Detected from
      // the resolved aria2c path; null when the binary's location
      // doesn't match a known package manager.
      installed_via: detectBinaryInstalledVia(probe.binPath),
      // BG-44: auto-start mechanism as a sub-object on the aria2 row.
      auto_start: detectAria2AutoStart(),
      reason: probe.running ? "match" : probe.installed ? "stopped" : "missing",
      outcome: probe.running
        ? "installed · current"
        : probe.installed
          ? "stopped"
          : "not installed",
      observation: probe.running ? "ok" : "failed",
      ...(probe.version ? { version: probe.version } : {}),
      ...(probe.binPath ? { path: probe.binPath } : {}),
      ...(probe.err ? { message: probe.err } : {}),
    },
  };
}

/**
 * networkquality: system binary, no version policy → current=null.
 * running is derived from "last probe used networkquality recently" —
 * the only honest signal we have without re-running the probe.
 */
export function buildNetworkqualityRow(state: ServerState): ComponentRow {
  const nq = installNs.networkqualityStatus();
  const probe = state.last_bandwidth_probe ?? null;
  const lastProbeAt = Number(state.last_bandwidth_probe_at ?? 0);
  const probeFresh = lastProbeAt > 0 && Date.now() / 1000 - lastProbeAt < 3600;
  const running = nq.installed
    ? probe?.source === "networkquality" && probeFresh
      ? true
      : null
    : false;
  return {
    result: {
      installed: Boolean(nq.installed),
      current: null,
      running,
      expected_running: null,
      managed_by: null,
      reason: nq.reason,
      outcome: nq.installed && nq.usable ? "installed · usable" : "unavailable",
      observation: nq.installed && nq.usable ? "ok" : "failed",
      message: nq.message,
      ...(nq.command ? { command: nq.command } : {}),
    },
  };
}
