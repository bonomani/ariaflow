import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  brewOutdatedFormula,
  buildPostUpgradeRestartSuffix,
  detectAriaflowInstalledVia,
  detectAriaflowManagedBy,
  detectBinaryInstalledVia,
  detectLaunchdLabel,
  findAria2c,
  resolvePkgManager,
  type AriaflowInstalledVia,
  type AriaflowManagedBy,
} from "@ariaflow/core";

export const ARIA2_SERVICE_TARGETS = new Set([
  "aria2-launchd",
  "aria2-systemd",
  "aria2-service",
]);

interface ActionDispatchResult {
  status: 200 | 202 | 409;
  body: Record<string, unknown>;
  /** Optional post-response side effect (process.exit, spawn, etc.). */
  after?: () => void;
}

const detached = (cmd: string, args: string[]): void => {
  spawn(cmd, args, { detached: true, stdio: "ignore" }).unref();
};

/**
 * BG-43: dispatch /api/lifecycle/ariaflow-server/restart per detected
 * supervisor. The actual restart happens after the response is sent
 * so the operator gets the 202 ack before launchctl/systemd kills us.
 */
export function dispatchAriaflowRestart(): ActionDispatchResult {
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
    // BG-61: prefer bootout+bootstrap over `kickstart -k`. kickstart
    // silently no-ops in some plist configurations (KeepAlive=false,
    // RunAtLoad combinations) and across macOS versions; the modern
    // unload+load is reliable. Fall back to kickstart only when the
    // plist isn't in ~/Library/LaunchAgents.
    const plistPath = join(homedir(), "Library", "LaunchAgents", `${label}.plist`);
    const useBootout = existsSync(plistPath);
    const domain = target.replace(/\/[^/]+$/, "");
    const after = useBootout
      ? () =>
          detached("sh", [
            "-c",
            `launchctl bootout ${target} 2>/dev/null; launchctl bootstrap ${domain} ${plistPath}`,
          ])
      : () => detached("launchctl", ["kickstart", "-k", target]);
    return {
      status: 202,
      body: {
        ok: true,
        action: "restart",
        managed_by: "launchd",
        launchctl_target: target,
        method: useBootout ? "bootout_bootstrap" : "kickstart",
      },
      after,
    };
  }
  if (managedBy === "systemd") {
    return {
      status: 202,
      body: { ok: true, action: "restart", managed_by: "systemd" },
      after: () => detached("systemctl", ["--user", "restart", "ariaflow-server"]),
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
export function dispatchAriaflowUpdate(
  opts: { autoRestart?: boolean } = {},
): ActionDispatchResult {
  const installedVia: AriaflowInstalledVia = detectAriaflowInstalledVia();
  // BG-62: chain a launchd bootout+bootstrap after the upgrade so the
  // running process picks up the new bottle. Suffix is null when not
  // applicable (non-launchd / plist not in ~/Library/LaunchAgents).
  const restartSuffix = opts.autoRestart ? buildPostUpgradeRestartSuffix() : null;
  const chained = (cmd: string): (() => void) =>
    restartSuffix
      // BG-65: ';' not '&&' so a no-op brew upgrade (stale cellar
      // case — running version lags installed) still triggers the
      // restart and realigns the running process to the cellar.
      ? () => detached("sh", ["-c", `${cmd} ; ${restartSuffix}`])
      : () => detached("sh", ["-c", cmd]);

  if (installedVia === "homebrew") {
    // BG-66: re-link before the restart so an "installed but not
    // linked" cellar (interrupted install / manual unlink / install.sh
    // race) is recovered too. Idempotent: succeeds whether the
    // formula is already linked, just installed, or both. 2>/dev/null
    // because brew prints diagnostics on the no-op path.
    const brew = resolvePkgManager("brew");
    const cmd = `${brew} upgrade ariaflow-server ; ${brew} link --overwrite ariaflow-server 2>/dev/null`;
    return {
      status: 202,
      body: {
        ok: true,
        action: "update",
        installed_via: "homebrew",
        auto_restart: Boolean(restartSuffix),
      },
      after: chained(cmd),
    };
  }
  if (installedVia === "pipx") {
    const cmd = `${resolvePkgManager("pipx")} upgrade ariaflow-server`;
    return {
      status: 202,
      body: {
        ok: true,
        action: "update",
        installed_via: "pipx",
        auto_restart: Boolean(restartSuffix),
      },
      after: chained(cmd),
    };
  }
  if (installedVia === "npm") {
    return {
      status: 202,
      body: { ok: true, action: "update", installed_via: "npm" },
      after: () => detached(resolvePkgManager("npm"), ["install", "-g", "@ariaflow/cli@latest"]),
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
 * BG-59: read-only probe of the package manager for an ariaflow-server
 * upgrade. Mirrors dispatchAriaflowUpdate's installer detection but
 * never dispatches `brew upgrade`. Returns 200 with the verdict on
 * supported installers; 409 on source/null.
 */
export async function dispatchAriaflowCheckUpdate(
  currentVersion: string,
): Promise<ActionDispatchResult> {
  const installedVia: AriaflowInstalledVia = detectAriaflowInstalledVia();
  if (installedVia === "homebrew") {
    const probe = await brewOutdatedFormula("ariaflow-server");
    return {
      status: 200,
      body: {
        ok: true,
        installed_via: "homebrew",
        current_version: probe.current_version ?? currentVersion,
        latest_version: probe.latest_version,
        update_available: probe.available,
        ...(probe.message ? { message: probe.message } : {}),
      },
    };
  }
  if (installedVia === "pipx" || installedVia === "npm") {
    return {
      status: 200,
      body: {
        ok: true,
        installed_via: installedVia,
        current_version: currentVersion,
        latest_version: null,
        update_available: null,
        message: `no check-update probe wired for installed_via=${installedVia}`,
      },
    };
  }
  if (installedVia === "source") {
    return {
      status: 409,
      body: {
        ok: false,
        error: "source_install",
        installed_via: "source",
        message: "running from a git checkout — no package manager to query",
      },
    };
  }
  return {
    status: 409,
    body: {
      ok: false,
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
export function dispatchAria2Update(): ActionDispatchResult {
  const installedVia = detectBinaryInstalledVia(findAria2c());

  if (installedVia === "homebrew") {
    return {
      status: 202,
      body: { ok: true, action: "update", installed_via: "homebrew" },
      after: () => detached(resolvePkgManager("brew"), ["upgrade", "aria2"]),
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
