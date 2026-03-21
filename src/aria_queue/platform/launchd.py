from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ARIA2_LABEL = "com.ariaflow.aria2"
ARIAFLOW_LABEL = "com.ariaflow.serve"


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def aria2_plist_path() -> Path:
    return launch_agents_dir() / f"{ARIA2_LABEL}.plist"


def ariaflow_plist_path() -> Path:
    return launch_agents_dir() / f"{ARIAFLOW_LABEL}.plist"


def aria2_session_dir() -> Path:
    return Path.home() / ".aria2"


def _launchctl_list(label: str) -> bool:
    if shutil.which("launchctl") is None:
        return False
    return subprocess.call(["launchctl", "list", label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def _launchctl_unload(plist: Path) -> None:
    uid = str(os.getuid())
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(plist)], check=False)
    subprocess.run(["launchctl", "unload", str(plist)], check=False)


def _launchctl_load(plist: Path) -> None:
    uid = str(os.getuid())
    try:
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], check=True)
    except subprocess.CalledProcessError:
        subprocess.run(["launchctl", "load", str(plist)], check=True)


def aria2_status() -> dict[str, bool]:
    version = None
    if _launchctl_list(ARIA2_LABEL):
        try:
            from ..core import aria_rpc

            version = aria_rpc("aria2.getVersion", timeout=5)["result"]["version"]
        except Exception:
            version = None
    return {
        "loaded": _launchctl_list(ARIA2_LABEL),
        "plist_exists": aria2_plist_path().exists(),
        "session_exists": (aria2_session_dir() / "session.txt").exists(),
        "version": version,
    }


def ariaflow_status() -> dict[str, bool]:
    return {
        "loaded": _launchctl_list(ARIAFLOW_LABEL),
        "plist_exists": ariaflow_plist_path().exists(),
    }


def is_macos() -> bool:
    return os.uname().sysname.lower() == "darwin"


def install_aria2_launchd(dry_run: bool = False) -> list[str]:
    bin_path = shutil.which("aria2c") or "/opt/homebrew/bin/aria2c"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{ARIA2_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{bin_path}</string>
    <string>--enable-rpc=true</string>
    <string>--rpc-listen-all=false</string>
    <string>--rpc-listen-port=6800</string>
    <string>--rpc-allow-origin-all=true</string>
    <string>--console-log-level=warn</string>
    <string>--summary-interval=0</string>
    <string>--dir={str(Path.home() / "Downloads")}</string>
    <string>--input-file={str(aria2_session_dir() / "session.txt")}</string>
    <string>--save-session={str(aria2_session_dir() / "session.txt")}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
"""
    commands = [
        f"mkdir -p {aria2_session_dir()} {Path.home() / 'Downloads'} {launch_agents_dir()}",
        f"touch {aria2_session_dir() / 'session.txt'}",
        f"cat > {aria2_plist_path()} <<'PLIST'\n{plist}PLIST",
        f"launchctl bootstrap gui/{os.getuid()} {aria2_plist_path()}",
    ]
    if dry_run:
        return commands
    subprocess.run(["mkdir", "-p", str(aria2_session_dir()), str(Path.home() / "Downloads"), str(launch_agents_dir())], check=True)
    (aria2_session_dir() / "session.txt").touch(exist_ok=True)
    aria2_plist_path().write_text(plist, encoding="utf-8")
    _launchctl_load(aria2_plist_path())
    return commands


def install_ariaflow_launchd(dry_run: bool = False) -> list[str]:
    bin_path = shutil.which("ariaflow") or "/opt/homebrew/bin/ariaflow"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{ARIAFLOW_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{bin_path}</string>
    <string>serve</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
"""
    commands = [
        f"mkdir -p {launch_agents_dir()}",
        f"cat > {ariaflow_plist_path()} <<'PLIST'\n{plist}PLIST",
        f"launchctl bootstrap gui/{os.getuid()} {ariaflow_plist_path()}",
    ]
    if dry_run:
        return commands
    subprocess.run(["mkdir", "-p", str(launch_agents_dir())], check=True)
    ariaflow_plist_path().write_text(plist, encoding="utf-8")
    _launchctl_load(ariaflow_plist_path())
    return commands


def uninstall_ariaflow_launchd(dry_run: bool = False) -> list[str]:
    commands = [f"launchctl unload {ariaflow_plist_path()}", f"rm -f {ariaflow_plist_path()}"]
    if dry_run:
        return commands
    _launchctl_unload(ariaflow_plist_path())
    if ariaflow_plist_path().exists():
        ariaflow_plist_path().unlink()
    return commands


def restart_ariaflow_launchd(dry_run: bool = False) -> list[str]:
    commands = [f"launchctl kickstart -k gui/{os.getuid()}/{ARIAFLOW_LABEL}"]
    if dry_run:
        return commands
    if ariaflow_plist_path().exists() or _launchctl_list(ARIAFLOW_LABEL):
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{ARIAFLOW_LABEL}"], check=False)
    return commands


def uninstall_aria2_launchd(dry_run: bool = False) -> list[str]:
    commands = [f"launchctl unload {aria2_plist_path()}", f"rm -f {aria2_plist_path()}", f"rm -rf {aria2_session_dir()}"]
    if dry_run:
        return commands
    _launchctl_unload(aria2_plist_path())
    if aria2_plist_path().exists():
        aria2_plist_path().unlink()
    if aria2_session_dir().exists():
        shutil.rmtree(aria2_session_dir(), ignore_errors=True)
    return commands
