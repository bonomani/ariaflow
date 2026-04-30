import { homedir } from "node:os";
import { join } from "node:path";

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

export interface InstallPaths {
  binPath: string;
  sessionDir: string;
  sessionFile: string;
  downloadDir: string;
  unitPath: string;
}

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
 * passes the resolved aria2c path. Mirrors platform/linux.py::_build_unit.
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

export const paths = {
  launchAgentsDir,
  launchdPlistPath,
  launchdSessionDir,
  systemdUserDir,
  systemdUnitPath,
  systemdSessionDir,
  defaultDownloadDir,
};
