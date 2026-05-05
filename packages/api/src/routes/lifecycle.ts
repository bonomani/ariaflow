import { existsSync } from "node:fs";
import { homedir } from "node:os";
import {
  detectServiceTarget,
  errorPayload,
  findAria2c,
  install as installNs,
  installAria2Service,
  uninstallAria2Service,
  type Aria2Client,
  type QueueItemRecord,
  type ServerState,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { ServerDeps } from "../server.js";
import type { RouteContext } from "./_context.js";

const PENDING = new Set(["queued", "waiting", "active"]);
const LAUNCHD_PLIST = `${homedir()}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`;

interface ComponentRow {
  result: Record<string, unknown>;
}

/**
 * BG-20 + BG-27 + BG-29: ariaflow-server itself. We're answering the
 * request, so all three axes are true and the version IS the
 * expected version. expected_running / managed_by stay null —
 * informational row, no daemon-style opinion to express.
 */
function buildAriaflowServerRow(deps: ServerDeps): ComponentRow {
  const expectedVersion = deps.version ?? "0.0.0";
  return {
    result: {
      installed: true,
      current: true,
      running: true,
      expected_running: null,
      managed_by: null,
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

async function probeAria2(client: Aria2Client | undefined): Promise<Aria2Probe> {
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
function buildAria2Row(
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
function buildNetworkqualityRow(state: ServerState): ComponentRow {
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

/**
 * aria2-launchd / aria2-systemd: a service registration, not an
 * installable binary — installed/current are null. running proxies
 * through aria2's RPC reachability: launchd's job is to keep aria2 up,
 * so if RPC works the unit is doing its job.
 */
function buildAria2LaunchdRow(aria2Running: boolean): ComponentRow {
  const target = detectServiceTarget();
  const home = homedir();
  const installedPath =
    target === "aria2-launchd"
      ? `${home}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`
      : target === "aria2-systemd"
        ? `${home}/.config/systemd/user/ariaflow-server-aria2.service`
        : null;
  const installedHere = installedPath ? existsSync(installedPath) : false;
  const running = installedHere ? aria2Running : false;
  return {
    result: {
      installed: null,
      current: null,
      running,
      expected_running: null,
      managed_by: installedHere ? "launchd" : null,
      reason: installedHere ? (aria2Running ? "match" : "stopped") : "missing",
      outcome: installedHere
        ? aria2Running
          ? "loaded"
          : "registered · not running"
        : "not installed",
      observation: installedHere && aria2Running ? "ok" : "unknown",
      ...(installedPath ? { path: installedPath } : {}),
    },
  };
}

const ARIA2_SERVICE_TARGETS = new Set([
  "aria2-launchd",
  "aria2-systemd",
  "aria2-service",
]);

export function registerLifecycleRoutes({ app, deps }: RouteContext): void {
  app.get("/api/lifecycle", async () => {
    const state = await deps.stateStore.load();
    const items = await deps.queueStore.load();
    const aria2Probe = await probeAria2(deps.aria2);

    return withMeta("GET", "/api/lifecycle", {
      ok: true,
      "ariaflow-server": buildAriaflowServerRow(deps),
      aria2: buildAria2Row(aria2Probe, state, items),
      networkquality: buildNetworkqualityRow(state),
      "aria2-launchd": buildAria2LaunchdRow(aria2Probe.running),
      session_id: state.session_id,
      session_started_at: state.session_started_at,
      session_last_seen_at: state.session_last_seen_at,
      session_closed_at: state.session_closed_at,
      session_closed_reason: state.session_closed_reason,
    });
  });

  app.post<{ Params: { target: string; action: string }; Querystring: { dry_run?: string } }>(
    "/api/lifecycle/:target/:action",
    async (req, reply) => {
      const target = req.params.target;
      const action = req.params.action;
      const dryRun = req.query?.dry_run === "1" || req.query?.dry_run === "true";

      const beforeState = await deps.stateStore.load();
      const before = { lifecycle: { state: beforeState } };
      try {
        let result: Record<string, unknown>;
        if (ARIA2_SERVICE_TARGETS.has(target) && action === "install") {
          const out = await installAria2Service({ dryRun });
          result = {
            [out.target]: {
              ok: out.ok,
              commands: out.commands,
              ...(out.results ? { results: out.results } : { dry_run: true }),
            },
          };
        } else if (ARIA2_SERVICE_TARGETS.has(target) && action === "uninstall") {
          const out = await uninstallAria2Service({ dryRun });
          result = {
            [out.target]: {
              ok: out.ok,
              commands: out.commands,
              ...(out.results ? { results: out.results } : { dry_run: true }),
            },
          };
        } else {
          return reply.code(400).send({
            error: "unsupported_action",
            target,
            action,
          });
        }

        await deps.actionLog.record({
          action: "lifecycle_action",
          target: target || "system",
          outcome: "changed",
          reason: action || "lifecycle_action",
          before,
          after: { target, action, result },
          detail: { target, action, dry_run: dryRun, result },
        });
        return { ok: true, target, action, dry_run: dryRun, result };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        await deps.actionLog.record({
          action: "lifecycle_action",
          target: target || "system",
          outcome: "failed",
          reason: "exception",
          before,
          detail: { error: message, target, action, dry_run: dryRun },
        });
        return reply
          .code(500)
          .send(errorPayload("lifecycle_action_failed", message));
      }
    },
  );
}
