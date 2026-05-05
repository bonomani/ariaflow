import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { spawn } from "node:child_process";
import {
  ACTIONS,
  detectAriaflowInstalledVia,
  detectAriaflowManagedBy,
  detectBinaryInstalledVia,
  detectLaunchdLabel,
  errorPayload,
  findAria2c,
  install as installNs,
  installAria2Service,
  uninstallAria2Service,
  type Aria2Client,
  type AriaflowInstalledVia,
  type AriaflowManagedBy,
  type QueueItemRecord,
  type ServerState,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { ServerDeps } from "../server.js";
import type { RouteContext } from "./_context.js";

const PENDING = new Set(["queued", "waiting", "active"]);
const LAUNCHD_PLIST = `${homedir()}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`;
const SYSTEMD_UNIT = `${homedir()}/.config/systemd/user/ariaflow-server-aria2.service`;

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

interface ComponentRow {
  result: Record<string, unknown>;
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
function buildAriaflowServerRow(deps: ServerDeps): ComponentRow {
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

const ARIA2_SERVICE_TARGETS = new Set([
  "aria2-launchd",
  "aria2-systemd",
  "aria2-service",
]);

interface ActionDispatchResult {
  status: 202 | 409;
  body: Record<string, unknown>;
  /** Optional post-response side effect (process.exit, spawn, etc.). */
  after?: () => void;
}

/**
 * BG-43: dispatch /api/lifecycle/ariaflow-server/restart per detected
 * supervisor. The actual restart happens after the response is sent
 * so the operator gets the 202 ack before launchctl/systemd kills us.
 */
function dispatchAriaflowRestart(): ActionDispatchResult {
  const managedBy: AriaflowManagedBy = detectAriaflowManagedBy();
  if (managedBy === "launchd") {
    const label = detectLaunchdLabel();
    if (!label) {
      return {
        status: 409,
        body: { error: "no_launchd_plist", managed_by: managedBy },
      };
    }
    const target = `gui/${process.getuid?.() ?? 0}/${label}`;
    return {
      status: 202,
      body: { ok: true, action: "restart", managed_by: "launchd", launchctl_target: target },
      // Detached so the parent doesn't block waiting for kickstart's
      // pipe; kickstart -k bounces us, the OS sends SIGTERM, fastify
      // is mid-flight returning the 202.
      after: () => {
        spawn("launchctl", ["kickstart", "-k", target], {
          detached: true,
          stdio: "ignore",
        }).unref();
      },
    };
  }
  if (managedBy === "systemd") {
    return {
      status: 202,
      body: { ok: true, action: "restart", managed_by: "systemd" },
      after: () => {
        spawn("systemctl", ["--user", "restart", "ariaflow-server"], {
          detached: true,
          stdio: "ignore",
        }).unref();
      },
    };
  }
  if (managedBy === "docker") {
    return {
      status: 202,
      body: { ok: true, action: "restart", managed_by: "docker", note: "exiting; orchestrator will restart" },
      after: () => setImmediate(() => process.exit(0)),
    };
  }
  if (managedBy === "external") {
    return {
      status: 409,
      body: {
        error: "manual_restart_required",
        managed_by: "external",
        message: "process is foregrounded by a shell, no supervisor to ask",
      },
    };
  }
  return {
    status: 409,
    body: {
      error: "unknown_supervisor",
      managed_by: null,
      message: "could not detect a supervisor for this process",
    },
  };
}

/**
 * BG-43: dispatch /api/lifecycle/ariaflow-server/update per detected
 * installer. The package manager runs detached; the running process
 * keeps serving until the next restart picks up the new version.
 */
function dispatchAriaflowUpdate(): ActionDispatchResult {
  const installedVia: AriaflowInstalledVia = detectAriaflowInstalledVia();
  const detached = (cmd: string, args: string[]) =>
    spawn(cmd, args, { detached: true, stdio: "ignore" }).unref();

  if (installedVia === "homebrew") {
    return {
      status: 202,
      body: { ok: true, action: "update", installed_via: "homebrew" },
      after: () => detached("brew", ["upgrade", "ariaflow-server"]),
    };
  }
  if (installedVia === "pipx") {
    return {
      status: 202,
      body: { ok: true, action: "update", installed_via: "pipx" },
      after: () => detached("pipx", ["upgrade", "ariaflow-server"]),
    };
  }
  if (installedVia === "npm") {
    return {
      status: 202,
      body: { ok: true, action: "update", installed_via: "npm" },
      after: () => detached("npm", ["install", "-g", "@ariaflow/cli@latest"]),
    };
  }
  if (installedVia === "source") {
    return {
      status: 409,
      body: {
        error: "source_install",
        installed_via: "source",
        message: "running from a git checkout — operator runs git pull && pnpm build",
      },
    };
  }
  return {
    status: 409,
    body: {
      error: "unknown_installer",
      installed_via: null,
      message: "could not detect an installer for this process",
    },
  };
}

/**
 * BG-46: dispatch /api/lifecycle/aria2/update per detected installer.
 * Mirrors dispatchAriaflowUpdate but targets the aria2 package and
 * never accepts a "source" verdict (third-party binary).
 */
function dispatchAria2Update(): ActionDispatchResult {
  const installedVia = detectBinaryInstalledVia(findAria2c());
  const detached = (cmd: string, args: string[]) =>
    spawn(cmd, args, { detached: true, stdio: "ignore" }).unref();

  if (installedVia === "homebrew") {
    return {
      status: 202,
      body: { ok: true, action: "update", installed_via: "homebrew" },
      after: () => detached("brew", ["upgrade", "aria2"]),
    };
  }
  if (installedVia === "pipx") {
    return {
      status: 409,
      body: {
        error: "no_pipx_aria2",
        installed_via: "pipx",
        message: "aria2 is not distributed via pipx",
      },
    };
  }
  if (installedVia === "npm") {
    return {
      status: 409,
      body: {
        error: "no_npm_aria2",
        installed_via: "npm",
        message: "aria2 is not distributed via npm",
      },
    };
  }
  return {
    status: 409,
    body: {
      error: "unknown_installer",
      installed_via: null,
      message: "could not detect an installer for the aria2 binary",
    },
  };
}

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

      // BG-43: ariaflow-server/{restart,update} dispatch via supervisor /
      // installer detection. Returns 202 on success and runs the side
      // effect (launchctl/systemctl/docker exit/brew upgrade/...) AFTER
      // the response is sent so the operator gets the ack before any
      // bounce. Dry-run returns the plan without executing.
      if (
        (target === "ariaflow-server" && (action === "restart" || action === "update")) ||
        (target === "aria2" && action === "update")
      ) {
        const dispatch =
          target === "aria2"
            ? dispatchAria2Update()
            : action === "restart"
              ? dispatchAriaflowRestart()
              : dispatchAriaflowUpdate();
        await deps.actionLog.record({
          action: ACTIONS.systemLifecycle,
          target: target || "system",
          outcome: dispatch.status === 202 ? "changed" : "blocked",
          reason: action,
          before,
          after: { target, action, dry_run: dryRun, ...dispatch.body },
          detail: { target, action, dry_run: dryRun, ...dispatch.body },
        });
        if (dispatch.status === 202 && !dryRun && dispatch.after) {
          // Schedule the side effect after the reply flushes.
          reply.raw.on("finish", () => {
            try {
              dispatch.after?.();
            } catch (err) {
              // Don't crash the server on a failed restart subprocess.
              console.error("BG-43 lifecycle action side effect failed:", err);
            }
          });
        }
        return reply.code(dispatch.status).send({
          ok: dispatch.status === 202,
          target,
          action,
          dry_run: dryRun,
          ...dispatch.body,
        });
      }

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
          return reply
            .code(400)
            .send(errorPayload("unsupported_action", `${target}/${action} not supported`, { target, action }));
        }

        await deps.actionLog.record({
          action: ACTIONS.systemLifecycle,
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
          action: ACTIONS.systemLifecycle,
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
