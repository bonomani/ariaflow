import { spawn } from "node:child_process";
import {
  detectAriaflowInstalledVia,
  detectAriaflowManagedBy,
  detectBinaryInstalledVia,
  detectLaunchdLabel,
  findAria2c,
  type AriaflowInstalledVia,
  type AriaflowManagedBy,
} from "@ariaflow/core";

export const ARIA2_SERVICE_TARGETS = new Set([
  "aria2-launchd",
  "aria2-systemd",
  "aria2-service",
]);

export interface ActionDispatchResult {
  status: 202 | 409;
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
    return {
      status: 202,
      body: { ok: true, action: "restart", managed_by: "launchd", launchctl_target: target },
      // Detached so the parent doesn't block waiting for kickstart's
      // pipe; kickstart -k bounces us, the OS sends SIGTERM, fastify
      // is mid-flight returning the 202.
      after: () => detached("launchctl", ["kickstart", "-k", target]),
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
export function dispatchAriaflowUpdate(): ActionDispatchResult {
  const installedVia: AriaflowInstalledVia = detectAriaflowInstalledVia();

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
export function dispatchAria2Update(): ActionDispatchResult {
  const installedVia = detectBinaryInstalledVia(findAria2c());

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
