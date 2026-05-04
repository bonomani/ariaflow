import { spawn as nodeSpawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { isLinux, isMacOS } from "../platform/detect.js";
import { which } from "../bonjour/bonjour.js";

export const ARIA2_LAUNCHD_LABEL = "com.ariaflow-server.aria2";
export const ARIA2_SYSTEMD_UNIT = "ariaflow-server-aria2.service";

const home = (): string => homedir();
const launchAgentsDir = (): string => join(home(), "Library", "LaunchAgents");
const launchdPlistPath = (): string => join(launchAgentsDir(), `${ARIA2_LAUNCHD_LABEL}.plist`);
const launchdSessionDir = (): string =>
  join(home(), "Library", "Application Support", "ariaflow-server", "aria2");

const systemdUserDir = (): string => join(home(), ".config", "systemd", "user");
const systemdUnitPath = (): string => join(systemdUserDir(), ARIA2_SYSTEMD_UNIT);
const systemdSessionDir = (): string =>
  join(home(), ".local", "share", "ariaflow-server", "aria2");

const defaultDownloadDir = (): string => join(home(), "Downloads");

/**
 * Render the launchd plist for the aria2 RPC daemon. Pure: caller passes
 * the resolved aria2c path (e.g. `which aria2c` or a Homebrew default).
 */
export function buildAria2Plist(opts: {
  binPath: string;
  sessionDir?: string;
  downloadDir?: string;
  rpcPort?: number;
}): string {
  const sessionDir = opts.sessionDir ?? launchdSessionDir();
  const downloadDir = opts.downloadDir ?? defaultDownloadDir();
  const port = opts.rpcPort ?? 6800;
  const sessionFile = join(sessionDir, "session.txt");
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${ARIA2_LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${opts.binPath}</string>
    <string>--enable-rpc=true</string>
    <string>--rpc-listen-all=false</string>
    <string>--rpc-listen-port=${port}</string>
    <string>--rpc-allow-origin-all=true</string>
    <string>--console-log-level=warn</string>
    <string>--summary-interval=0</string>
    <string>--dir=${downloadDir}</string>
    <string>--input-file=${sessionFile}</string>
    <string>--save-session=${sessionFile}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
`;
}

/**
 * Render the systemd user unit for the aria2 RPC daemon. Pure: caller
 * passes the resolved aria2c path.
 */
export function buildAria2SystemdUnit(opts: {
  binPath: string;
  sessionDir?: string;
  downloadDir?: string;
  rpcPort?: number;
}): string {
  const sessionDir = opts.sessionDir ?? systemdSessionDir();
  const downloadDir = opts.downloadDir ?? defaultDownloadDir();
  const port = opts.rpcPort ?? 6800;
  const sessionFile = join(sessionDir, "session.txt");
  return `[Unit]
Description=aria2 RPC daemon (managed by ariaflow-server)
After=network.target

[Service]
Type=simple
ExecStart=${opts.binPath} \\
  --enable-rpc=true \\
  --rpc-listen-all=false \\
  --rpc-listen-port=${port} \\
  --rpc-allow-origin-all=true \\
  --console-log-level=warn \\
  --summary-interval=0 \\
  --dir=${downloadDir} \\
  --input-file=${sessionFile} \\
  --save-session=${sessionFile}
Restart=on-failure

[Install]
WantedBy=default.target
`;
}

/**
 * Plan the install commands for the launchd aria2 service. Pure — does
 * not execute anything. Suitable for `--dry-run` flows and parity tests.
 */
export function planLaunchdInstall(binPath: string): string[] {
  const plist = buildAria2Plist({ binPath });
  return [
    `mkdir -p ${launchdSessionDir()} ${defaultDownloadDir()} ${launchAgentsDir()}`,
    `touch ${join(launchdSessionDir(), "session.txt")}`,
    `cat > ${launchdPlistPath()} <<'PLIST'\n${plist}PLIST`,
    `launchctl bootstrap gui/$(id -u) ${launchdPlistPath()}`,
  ];
}

export function planLaunchdUninstall(): string[] {
  return [
    `launchctl bootout gui/$(id -u)/${ARIA2_LAUNCHD_LABEL} 2>/dev/null || true`,
    `rm -f ${launchdPlistPath()}`,
  ];
}

export function planSystemdInstall(binPath: string): string[] {
  const unit = buildAria2SystemdUnit({ binPath });
  return [
    `mkdir -p ${systemdSessionDir()} ${defaultDownloadDir()} ${systemdUserDir()}`,
    `touch ${join(systemdSessionDir(), "session.txt")}`,
    `cat > ${systemdUnitPath()} <<'UNIT'\n${unit}UNIT`,
    `systemctl --user daemon-reload`,
    `systemctl --user enable --now ${ARIA2_SYSTEMD_UNIT}`,
  ];
}

export function planSystemdUninstall(): string[] {
  return [
    `systemctl --user disable --now ${ARIA2_SYSTEMD_UNIT}`,
    `rm -f ${systemdUnitPath()}`,
    `systemctl --user daemon-reload`,
  ];
}

export type ServiceTarget = "aria2-launchd" | "aria2-systemd" | null;

/**
 * Pick the right service-management target for the current platform.
 * Returns null on Windows / unsupported platforms.
 */
export function detectServiceTarget(): ServiceTarget {
  if (isMacOS()) return "aria2-launchd";
  if (isLinux()) return "aria2-systemd";
  return null;
}

/**
 * Resolve the aria2c binary on PATH (or fall back to the first
 * Homebrew/Linux-default location). Returns null when nothing is found.
 */
export function findAria2c(env: NodeJS.ProcessEnv = process.env): string | null {
  // Augment PATH with the typical brew/system locations before
  // running `which`. launchd's default PATH is /usr/bin:/bin:/usr/sbin:/sbin
  // which would otherwise miss aria2c installed via Homebrew.
  const augmented = {
    ...env,
    PATH: [env.PATH, "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
      .filter(Boolean)
      .join(":"),
  };
  const onPath = which("aria2c", augmented);
  if (onPath) return onPath;
  for (const candidate of [
    "/opt/homebrew/bin/aria2c",
    "/usr/local/bin/aria2c",
    "/usr/bin/aria2c",
  ]) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

export interface ShellExecResult {
  command: string;
  ok: boolean;
  exitCode: number | null;
  stderr: string;
}

/**
 * Execute a list of shell commands sequentially. Each runs through
 * `sh -c` so the heredoc / pipe forms in the install plans work
 * unchanged. Stops on the first non-zero exit by default; pass
 * stopOnError=false to drain the whole list (used for uninstall, where
 * a partial cleanup is still better than an early abort).
 */
export async function runShellPlan(
  commands: readonly string[],
  opts: {
    stopOnError?: boolean;
    spawn?: typeof nodeSpawn;
    cwd?: string;
  } = {},
): Promise<ShellExecResult[]> {
  const spawn = opts.spawn ?? nodeSpawn;
  const stopOnError = opts.stopOnError ?? true;
  const out: ShellExecResult[] = [];
  for (const command of commands) {
    const res = await runOne(spawn, command, opts.cwd);
    out.push(res);
    if (stopOnError && !res.ok) break;
  }
  return out;
}

function runOne(
  spawn: typeof nodeSpawn,
  command: string,
  cwd?: string,
): Promise<ShellExecResult> {
  return new Promise((resolve) => {
    const proc = spawn("sh", ["-c", command], {
      stdio: ["ignore", "ignore", "pipe"],
      ...(cwd ? { cwd } : {}),
    });
    const errChunks: Buffer[] = [];
    proc.stderr?.on("data", (chunk: Buffer) => errChunks.push(chunk));
    proc.on("error", (err) =>
      resolve({
        command,
        ok: false,
        exitCode: null,
        stderr: err.message,
      }),
    );
    proc.on("close", (code) =>
      resolve({
        command,
        ok: code === 0,
        exitCode: code,
        stderr: Buffer.concat(errChunks).toString("utf8"),
      }),
    );
  });
}

export interface InstallServiceResult {
  target: Exclude<ServiceTarget, null>;
  commands: string[];
  /** Per-command exec result; absent when dryRun=true. */
  results?: ShellExecResult[];
  /** True when dryRun=true OR every command exited 0. */
  ok: boolean;
}

/**
 * Plan + (optionally) execute the platform-appropriate aria2 service
 * install. Pass dryRun=true to get the plan back without running it.
 */
export async function installAria2Service(opts: {
  dryRun?: boolean;
  binPath?: string;
  spawn?: typeof nodeSpawn;
} = {}): Promise<InstallServiceResult> {
  const target = detectServiceTarget();
  if (!target) {
    throw new Error("aria2 service install not supported on this platform");
  }
  const binPath = opts.binPath ?? findAria2c() ?? "aria2c";
  const commands =
    target === "aria2-launchd"
      ? planLaunchdInstall(binPath)
      : planSystemdInstall(binPath);
  if (opts.dryRun) return { target, commands, ok: true };
  const results = await runShellPlan(commands, {
    stopOnError: true,
    ...(opts.spawn ? { spawn: opts.spawn } : {}),
  });
  return { target, commands, results, ok: results.every((r) => r.ok) };
}

export async function uninstallAria2Service(opts: {
  dryRun?: boolean;
  spawn?: typeof nodeSpawn;
} = {}): Promise<InstallServiceResult> {
  const target = detectServiceTarget();
  if (!target) {
    throw new Error("aria2 service uninstall not supported on this platform");
  }
  const commands =
    target === "aria2-launchd" ? planLaunchdUninstall() : planSystemdUninstall();
  if (opts.dryRun) return { target, commands, ok: true };
  // Uninstall: drain the whole plan even if a step fails (the unit may
  // already be disabled; the plist may already be removed).
  const results = await runShellPlan(commands, {
    stopOnError: false,
    ...(opts.spawn ? { spawn: opts.spawn } : {}),
  });
  return { target, commands, results, ok: results.every((r) => r.ok) };
}
