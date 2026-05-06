import { spawn } from "node:child_process";
import {
  ACTIONS,
  TARGETS,
  buildPostUpgradeRestartSuffix,
  detectAriaflowInstalledVia,
  prefValue,
  resolvePkgManager,
  type AriaflowInstalledVia,
} from "@ariaflow/core";
import type { CliContext } from "../context.js";

interface AutoUpdateController {
  running: () => boolean;
  launch: () => void;
  stop: () => void;
}

interface OutdatedResult {
  available: boolean;
  message?: string;
}

/**
 * Check whether the package manager has a newer ariaflow-server
 * version available. Best-effort + non-blocking: a non-zero exit or
 * unrecognized installer simply reports `available: false`.
 *
 * brew: `brew outdated --json ariaflow-server` exits 0 with a non-empty
 *       `formulae` array when an upgrade exists.
 * pipx / npm / source: not yet wired — phase 3 v1 covers brew only,
 * which matches the dominant install path on the project's macOS hosts.
 */
function brewOutdated(): Promise<OutdatedResult> {
  return new Promise((resolve) => {
    const proc = spawn(resolvePkgManager("brew"), ["outdated", "--json=v2", "ariaflow-server"], {
      stdio: ["ignore", "pipe", "ignore"],
    });
    const chunks: Buffer[] = [];
    proc.stdout?.on("data", (c: Buffer) => chunks.push(c));
    proc.on("error", () => resolve({ available: false, message: "brew not on PATH" }));
    proc.on("close", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        const parsed = JSON.parse(raw) as { formulae?: unknown[] };
        const available = Array.isArray(parsed.formulae) && parsed.formulae.length > 0;
        resolve({ available });
      } catch {
        resolve({ available: false, message: "unparseable brew output" });
      }
    });
  });
}

async function checkForUpdate(installedVia: AriaflowInstalledVia): Promise<OutdatedResult> {
  if (installedVia === "homebrew") return brewOutdated();
  return { available: false, message: `no outdated check for installed_via=${installedVia ?? "null"}` };
}

function applyUpdate(installedVia: AriaflowInstalledVia, autoRestart: boolean): void {
  // Mirrors BG-43's manual /api/lifecycle/ariaflow-server/update path:
  // detached + unref so the running process keeps serving until the
  // next supervisor-driven restart picks up the new binary. BG-62
  // chains a launchd bootout+bootstrap when the pref + supervisor
  // both say so, so the new bottle takes effect without operator action.
  const detached = (cmd: string, args: string[]): void => {
    spawn(cmd, args, { detached: true, stdio: "ignore" }).unref();
  };
  if (installedVia !== "homebrew") return;
  const brew = resolvePkgManager("brew");
  const restartSuffix = autoRestart ? buildPostUpgradeRestartSuffix() : null;
  if (restartSuffix) {
    // BG-65: ';' not '&&' so a no-op upgrade (stale cellar) still restarts.
    detached("sh", ["-c", `${brew} upgrade ariaflow-server ; ${restartSuffix}`]);
  } else {
    detached(brew, ["upgrade", "ariaflow-server"]);
  }
}

const HOUR_S = 3600;

/**
 * BG-45 phase 3: periodic check for newer ariaflow-server versions.
 * Drives the same package-manager invocation as the manual update
 * button. Cadence is set by the `auto_update_check_hours` preference;
 * the gate is the `auto_update` boolean (false → no check fires).
 *
 * The loop reloads the declaration every tick so flipping the toggle
 * via /api/declaration takes effect without a restart.
 */
export function createAutoUpdateController(ctx: CliContext): AutoUpdateController {
  let timer: NodeJS.Timeout | undefined;
  let inFlight = false;

  const tick = async (): Promise<void> => {
    if (inFlight) return;
    inFlight = true;
    try {
      const declaration = await ctx.declaration.load();
      const enabled = Boolean(prefValue(declaration, "auto_update", false));
      if (!enabled) return;
      const installedVia = detectAriaflowInstalledVia();
      const result = await checkForUpdate(installedVia);
      await ctx.actions.record({
        action: ACTIONS.autoUpdateCheck,
        target: TARGETS.system,
        outcome: result.available ? "changed" : "unchanged",
        reason: installedVia ?? "unknown_installer",
        detail: { installed_via: installedVia, available: result.available, message: result.message },
      });
      if (result.available) {
        const autoRestart = Boolean(
          prefValue(declaration, "auto_restart_after_upgrade", true),
        );
        applyUpdate(installedVia, autoRestart);
        await ctx.actions.record({
          action: ACTIONS.autoUpdateApplied,
          target: TARGETS.system,
          outcome: "changed",
          reason: installedVia ?? "unknown_installer",
          detail: { installed_via: installedVia },
        });
      }
    } catch (err) {
      await ctx.actions.record({
        action: ACTIONS.autoUpdateCheck,
        target: TARGETS.system,
        outcome: "failed",
        reason: "exception",
        detail: { error: err instanceof Error ? err.message : String(err) },
      });
    } finally {
      inFlight = false;
    }
  };

  const launch = (): void => {
    if (timer) return;
    // Read the cadence at launch time. A change to
    // auto_update_check_hours requires a restart — keeps the timer
    // simple and avoids a re-arm dance on every preference patch.
    void ctx.declaration.load().then((declaration) => {
      const hours = Number(prefValue(declaration, "auto_update_check_hours", 24));
      const intervalMs = Math.max(1, hours) * HOUR_S * 1000;
      // First tick deferred by one interval so cmdServe boot stays
      // snappy; the supervisor takes care of recurring waking up.
      timer = setInterval(() => void tick(), intervalMs);
      timer.unref();
    });
  };

  const stop = (): void => {
    if (!timer) return;
    clearInterval(timer);
    timer = undefined;
  };

  return { running: () => Boolean(timer), launch, stop };
}
