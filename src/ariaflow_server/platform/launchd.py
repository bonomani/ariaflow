from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ARIA2_LABEL = "com.ariaflow-server.aria2"


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def launchd_aria2_plist_path() -> Path:
    return launch_agents_dir() / f"{ARIA2_LABEL}.plist"


def launchd_aria2_session_dir() -> Path:
    return Path.home() / ".aria2"


def _launchctl_list(label: str) -> bool:
    if shutil.which("launchctl") is None:
        return False
    return (
        subprocess.call(
            ["launchctl", "list", label],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


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


def launchd_aria2_status() -> dict[str, bool]:
    version = None
    if _launchctl_list(ARIA2_LABEL):
        try:
            from ..core import aria2_get_version

            version = aria2_get_version(timeout=5)["version"]
        except Exception:
            version = None
    return {
        "loaded": _launchctl_list(ARIA2_LABEL),
        "plist_exists": launchd_aria2_plist_path().exists(),
        "session_exists": (launchd_aria2_session_dir() / "session.txt").exists(),
        "version": version,
    }


from .detect import default_downloads_dir as _default_dl  # noqa: F401
from .detect import is_macos  # noqa: F401 — re-exported for backwards compat


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
    <string>--dir={str(_default_dl())}</string>
    <string>--input-file={str(launchd_aria2_session_dir() / "session.txt")}</string>
    <string>--save-session={str(launchd_aria2_session_dir() / "session.txt")}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
"""
    commands = [
        f"mkdir -p {launchd_aria2_session_dir()} {_default_dl()} {launch_agents_dir()}",
        f"touch {launchd_aria2_session_dir() / 'session.txt'}",
        f"cat > {launchd_aria2_plist_path()} <<'PLIST'\n{plist}PLIST",
        f"launchctl bootstrap gui/{os.getuid()} {launchd_aria2_plist_path()}",
    ]
    if dry_run:
        return commands
    subprocess.run(
        [
            "mkdir",
            "-p",
            str(launchd_aria2_session_dir()),
            str(_default_dl()),
            str(launch_agents_dir()),
        ],
        check=True,
    )
    (launchd_aria2_session_dir() / "session.txt").touch(exist_ok=True)
    launchd_aria2_plist_path().write_text(plist, encoding="utf-8")
    _launchctl_load(launchd_aria2_plist_path())
    return commands


def uninstall_aria2_launchd(dry_run: bool = False) -> list[str]:
    commands = [
        f"launchctl unload {launchd_aria2_plist_path()}",
        f"rm -f {launchd_aria2_plist_path()}",
        f"rm -rf {launchd_aria2_session_dir()}",
    ]
    if dry_run:
        return commands
    _launchctl_unload(launchd_aria2_plist_path())
    if launchd_aria2_plist_path().exists():
        launchd_aria2_plist_path().unlink()
    if launchd_aria2_session_dir().exists():
        shutil.rmtree(launchd_aria2_session_dir(), ignore_errors=True)
    return commands
