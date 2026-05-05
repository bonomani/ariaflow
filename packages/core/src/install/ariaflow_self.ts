import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * BG-43: orthogonal axes describing how the running ariaflow-server
 * process is supervised and how it was installed. Surface on
 * `/api/lifecycle.ariaflow-server.result` so the dashboard knows
 * whether to show Restart / Update buttons.
 */
export type AriaflowManagedBy =
  | "launchd"
  | "systemd"
  | "docker"
  | "external"
  | null;

export type AriaflowInstalledVia =
  | "homebrew"
  | "pipx"
  | "npm"
  | "source"
  | null;

/** Brew-services plist name + the spec's generic name. */
const LAUNCHD_LABELS = ["homebrew.mxcl.ariaflow-server", "com.ariaflow-server"] as const;

/**
 * Detect who supervises this process. PPID==1 on macOS means launchd
 * is our parent; on Linux it could be init or systemd. We disambiguate
 * via filesystem signals (a plist for launchd, /.dockerenv for docker,
 * etc.).
 */
export function detectAriaflowManagedBy(
  env: NodeJS.ProcessEnv = process.env,
): AriaflowManagedBy {
  // Docker first — covers both Linux and macOS docker desktop.
  if (existsSync("/.dockerenv")) return "docker";
  const ppid = process.ppid;
  // launchd: a plist exists AND we were spawned by launchd (PPID 1).
  if (process.platform === "darwin") {
    const dir = join(homedir(), "Library", "LaunchAgents");
    const plistFound = LAUNCHD_LABELS.some((label) =>
      existsSync(join(dir, `${label}.plist`)),
    );
    if (plistFound && ppid === 1) return "launchd";
  }
  // systemd-user: heuristic — XDG_RUNTIME_DIR is set in user systemd
  // sessions, and INVOCATION_ID is exported when the unit's
  // ExecStart is what spawned us.
  if (process.platform === "linux" && env.INVOCATION_ID && ppid === 1) {
    return "systemd";
  }
  if (ppid === 1) return "external"; // started by some init system we don't recognize
  if (ppid > 1) return "external"; // foregrounded by a shell, etc.
  return null;
}

/**
 * Detect how this process was installed. Resolved from process.argv[1]
 * (the entry script path) — `node /path/to/script.js ...`.
 */
export function detectAriaflowInstalledVia(
  argvScript: string = process.argv[1] ?? "",
  env: NodeJS.ProcessEnv = process.env,
): AriaflowInstalledVia {
  if (!argvScript) return null;
  // Homebrew: under $(brew --prefix), typically /opt/homebrew or
  // /usr/local. The Cellar path is the canonical install location.
  const brewPrefix = env.HOMEBREW_PREFIX || (process.platform === "darwin" ? "/opt/homebrew" : "/home/linuxbrew/.linuxbrew");
  if (argvScript.startsWith(`${brewPrefix}/`) || argvScript.includes("/Cellar/ariaflow-server/")) {
    return "homebrew";
  }
  // pipx: ~/.local/pipx/venvs/...
  if (argvScript.includes("/.local/pipx/venvs/")) return "pipx";
  // global npm: $(npm prefix -g)/lib/node_modules/...
  if (argvScript.includes("/lib/node_modules/")) return "npm";
  // source: anything resolving inside a git working tree (we look up
  // for a .git dir from the script's parent).
  if (isInsideGitTree(argvScript)) return "source";
  return null;
}

function isInsideGitTree(filePath: string): boolean {
  let dir = filePath.replace(/\/[^/]+$/, "");
  for (let i = 0; i < 8; i++) {
    if (existsSync(join(dir, ".git"))) return true;
    const parent = dir.replace(/\/[^/]+$/, "");
    if (parent === dir || !parent) return false;
    dir = parent;
  }
  return false;
}

/**
 * Resolve the launchd label of the actually-installed plist. Returns
 * the first match from LAUNCHD_LABELS, or null when no plist exists.
 * Used to construct the kickstart target string.
 */
export function detectLaunchdLabel(): string | null {
  const dir = join(homedir(), "Library", "LaunchAgents");
  for (const label of LAUNCHD_LABELS) {
    if (existsSync(join(dir, `${label}.plist`))) return label;
  }
  return null;
}
