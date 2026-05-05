import { existsSync } from "node:fs";
import { homedir } from "node:os";
import {
  detectServiceTarget,
  errorPayload,
  findAria2c,
  install as installNs,
  installAria2Service,
  uninstallAria2Service,
} from "@ariaflow/core";
import { withMeta } from "../freshness.js";
import type { RouteContext } from "./_context.js";

export function registerLifecycleRoutes({ app, deps }: RouteContext): void {
  app.get("/api/lifecycle", async () => {
    const state = await deps.stateStore.load();

    // BG-20 + BG-27: every component record nests under `result`. BG-27
    // adds three orthogonal axes — `installed` / `current` / `running`
    // (each `bool | null`, with `null` for axes that don't apply) —
    // alongside the BG-20 reason/outcome/message strings. The dashboard
    // can drive headline rendering off the booleans and use the
    // strings for detail rendering.

    const expectedVersion = deps.version ?? "0.0.0";

    // ariaflow-server: we're answering the request, so all three axes
    // are true and the version IS the expected version.
    const ariaflowServer = {
      result: {
        installed: true,
        current: true,
        running: true,
        // BG-29: not on-demand and not externally managed; null = "no opinion".
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

    // aria2: split "binary on disk" (installed) from "RPC reachable"
    // (running). `current` only meaningful when installed=true; we
    // don't ship an expected aria2 version so it stays null (true if
    // RPC succeeds, since whatever's there is what we use).
    const aria2BinPath = findAria2c();
    const aria2Installed = Boolean(aria2BinPath);
    let aria2Running = false;
    let aria2Version: string | null = null;
    let aria2Err: string | null = null;
    if (deps.aria2) {
      try {
        const v = await deps.aria2.call<{ version: string }>("aria2.getVersion");
        aria2Running = true;
        aria2Version = v.version;
      } catch (err) {
        aria2Err = err instanceof Error ? err.message : String(err);
      }
    }
    const aria2Current = aria2Installed ? (aria2Running ? true : null) : null;

    // BG-29(a): aria2 is on-demand. expected_running = "would the
    // scheduler want aria2 up right now?" — true while there's work
    // pending or a tick is mid-dispatch. The dashboard's verdict
    // truth-table reads this against `running` to distinguish a
    // healthy idle from a genuine fault.
    const queueItems = await deps.queueStore.load();
    const PENDING = new Set(["queued", "waiting", "active"]);
    const workPending = queueItems.some((i) => PENDING.has(String(i.status ?? "")));
    const aria2ExpectedRunning =
      Boolean(state.running) || Boolean(state.active_gid) || workPending;

    // BG-29(b): managed_by = "who actually spawned the running aria2".
    // We never fork aria2 ourselves today, so the "ariaflow" branch is
    // unreachable in current code; a launchd plist on disk is the only
    // signal we have for "auto-start (launchd)" — anything else is
    // attributed to "external". null when not running.
    const launchdPath = `${homedir()}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`;
    const launchdInstalled = existsSync(launchdPath);
    const aria2ManagedBy: "ariaflow" | "launchd" | "external" | null = aria2Running
      ? launchdInstalled
        ? "launchd"
        : "external"
      : null;

    const aria2Result: Record<string, unknown> = {
      installed: aria2Installed,
      current: aria2Current,
      running: aria2Running,
      expected_running: aria2ExpectedRunning,
      managed_by: aria2ManagedBy,
      reason: aria2Running ? "match" : aria2Installed ? "stopped" : "missing",
      outcome: aria2Running
        ? "installed · current"
        : aria2Installed
          ? "stopped"
          : "not installed",
      observation: aria2Running ? "ok" : "failed",
      ...(aria2Version ? { version: aria2Version } : {}),
      ...(aria2BinPath ? { path: aria2BinPath } : {}),
      ...(aria2Err ? { message: aria2Err } : {}),
    };

    // networkquality: system binary, no version policy → current=null.
    // running is derived from "last probe used networkquality recently"
    // — the only honest signal we have without re-running the probe.
    const nq = installNs.networkqualityStatus();
    const probe = state.last_bandwidth_probe ?? null;
    const lastProbeAt = Number(state.last_bandwidth_probe_at ?? 0);
    const probeFresh = lastProbeAt > 0 && Date.now() / 1000 - lastProbeAt < 3600;
    const nqRunning = nq.installed
      ? probe?.source === "networkquality" && probeFresh
        ? true
        : null // installed but no recent probe → "unknown", not "stopped"
      : false;
    const networkquality = {
      result: {
        installed: Boolean(nq.installed),
        current: null,
        running: nqRunning,
        // BG-29: on-demand probe, not a daemon — null on both axes.
        expected_running: null,
        managed_by: null,
        reason: nq.reason, // "ready" | "missing"
        outcome: nq.installed && nq.usable ? "installed · usable" : "unavailable",
        observation: nq.installed && nq.usable ? "ok" : "failed",
        message: nq.message,
        ...(nq.command ? { command: nq.command } : {}),
      },
    };

    // aria2-launchd / aria2-systemd: it's a service registration, not
    // an installable binary — installed/current are null. running
    // proxies through aria2's RPC reachability: launchd's job is to
    // keep aria2 up, so if RPC works the unit is doing its job.
    const target = detectServiceTarget();
    const home = homedir();
    const installedPath =
      target === "aria2-launchd"
        ? `${home}/Library/LaunchAgents/com.ariaflow-server.aria2.plist`
        : target === "aria2-systemd"
          ? `${home}/.config/systemd/user/ariaflow-server-aria2.service`
          : null;
    const installedHere = installedPath ? existsSync(installedPath) : false;
    const launchdRunning = installedHere ? aria2Running : false;
    const aria2Launchd = {
      result: {
        installed: null,
        current: null,
        running: launchdRunning,
        // BG-29: informational row — keep `expected_running` null so
        // the dashboard's verdict table treats it as "no opinion"
        // instead of flagging an idle plist as faulty.
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

    return withMeta("GET", "/api/lifecycle", {
      ok: true,
      "ariaflow-server": ariaflowServer,
      aria2: { result: aria2Result },
      networkquality,
      "aria2-launchd": aria2Launchd,
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

      const ARIA2_SERVICE_TARGETS = new Set([
        "aria2-launchd",
        "aria2-systemd",
        "aria2-service",
      ]);
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
