from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ARIA2_LABEL = "com.ariaflow.aria2"
ARIAFLOW_LABEL = "com.ariaflow.serve"


def ucc_envelope(
    *,
    target: str,
    observed: bool,
    outcome: str,
    completion: str | None = None,
    reason: str = "aggregate",
    detail: str | None = None,
    commands: list[str] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "observation": "ok" if observed else "failed",
        "outcome": outcome,
        "reason": reason,
        "target": target,
    }
    if completion is not None:
        result["completion"] = completion
    if detail is not None:
        result["message"] = detail
    if commands is not None:
        result["commands"] = commands
    return {
        "meta": {"contract": "UCC", "version": "2.0", "target": target},
        "result": result,
    }


def ucc_record(
    *,
    target: str,
    observed: bool,
    outcome: str,
    completion: str | None = None,
    reason: str = "aggregate",
    detail: str | None = None,
    commands: list[str] | None = None,
) -> dict[str, object]:
    return ucc_envelope(
        target=target,
        observed=observed,
        outcome=outcome,
        completion=completion,
        reason=reason,
        detail=detail,
        commands=commands,
    )


def is_macos() -> bool:
    return os.uname().sysname.lower() == "darwin"


def brew_is_installed(package: str) -> bool:
    return shutil.which("brew") is not None and subprocess.call(["brew", "list", package], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def ensure_brew_tap(tap: str = "bonomani/ariaflow", dry_run: bool = False) -> list[str]:
    commands = [["brew", "tap", tap]]
    if dry_run:
        return [" ".join(cmd) for cmd in commands]
    subprocess.run(commands[0], check=True)
    return [" ".join(commands[0])]


def homebrew_install_ariaflow(dry_run: bool = False) -> list[str]:
    commands = [["brew", "tap", "bonomani/ariaflow"], ["brew", "install", "ariaflow"]]
    if dry_run:
        return [" ".join(cmd) for cmd in commands]
    for cmd in commands:
        subprocess.run(cmd, check=True)
    return [" ".join(cmd) for cmd in commands]


def homebrew_update_ariaflow(dry_run: bool = False) -> list[str]:
    commands = [["brew", "upgrade", "ariaflow"]]
    if dry_run:
        return [" ".join(cmd) for cmd in commands]
    try:
        subprocess.run(commands[0], check=True)
    except subprocess.CalledProcessError:
        subprocess.run(["brew", "install", "ariaflow"], check=True)
    return [" ".join(cmd) for cmd in commands]


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
    subprocess.run(["launchctl", "unload", str(plist)], check=False)


def _launchctl_load(plist: Path) -> None:
    subprocess.run(["launchctl", "load", str(plist)], check=True)


def aria2_status() -> dict[str, bool]:
    return {
        "loaded": _launchctl_list(ARIA2_LABEL),
        "plist_exists": aria2_plist_path().exists(),
        "session_exists": (aria2_session_dir() / "session.txt").exists(),
    }


def ariaflow_status() -> dict[str, bool]:
    return {
        "loaded": _launchctl_list(ARIAFLOW_LABEL),
        "plist_exists": ariaflow_plist_path().exists(),
    }


def ariaflow_web_enabled() -> bool:
    return ariaflow_status()["plist_exists"] or ariaflow_status()["loaded"]


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
        f"launchctl load {aria2_plist_path()}",
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
        f"launchctl load {ariaflow_plist_path()}",
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


def install_all(dry_run: bool = False, include_web: bool = False) -> dict[str, dict[str, object]]:
    if not dry_run and not is_macos():
        raise RuntimeError("install is only supported on macOS")
    ariaflow_cmds = homebrew_install_ariaflow(dry_run=dry_run)
    aria2_cmds = install_aria2_launchd(dry_run=dry_run)
    plan = {
        "ariaflow": ucc_record(
            target="ariaflow",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="install",
            detail="ariaflow package installed or queued for installation",
            commands=ariaflow_cmds,
        ),
        "aria2-launchd": ucc_record(
            target="aria2-launchd",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="install",
            detail="aria2 launchd service installed or queued for installation",
            commands=aria2_cmds,
        ),
    }
    if include_web:
        serve_cmds = install_ariaflow_launchd(dry_run=dry_run)
        plan["ariaflow-serve-launchd"] = ucc_record(
            target="ariaflow-serve-launchd",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="install",
            detail="ariaflow web UI launchd service installed or queued for installation",
            commands=serve_cmds,
        )
    return plan


def status_all() -> dict[str, dict[str, object]]:
    ariaflow_installed = brew_is_installed("ariaflow")
    aria2 = aria2_status()
    serve = ariaflow_status()
    plan = {
        "ariaflow": ucc_record(
            target="ariaflow",
            observed=True,
            outcome="converged" if ariaflow_installed else "unchanged",
            completion="complete",
            reason="match" if ariaflow_installed else "missing",
            detail="ariaflow package installed" if ariaflow_installed else "ariaflow package absent",
        ),
        "aria2-launchd": ucc_record(
            target="aria2-launchd",
            observed=True,
            outcome="converged" if aria2["loaded"] else "unchanged",
            completion="complete",
            reason="match" if aria2["loaded"] else "missing",
            detail="aria2 launchd loaded" if aria2["loaded"] else "aria2 launchd absent",
        ),
    }
    if serve["loaded"] or serve["plist_exists"]:
        plan["ariaflow-serve-launchd"] = ucc_record(
            target="ariaflow-serve-launchd",
            observed=True,
            outcome="converged" if serve["loaded"] else "unchanged",
            completion="complete",
            reason="match" if serve["loaded"] else "missing",
            detail="ariaflow web launchd loaded" if serve["loaded"] else "ariaflow web launchd absent",
        )
    else:
        plan["ariaflow-serve-launchd"] = ucc_record(
            target="ariaflow-serve-launchd",
            observed=True,
            outcome="skipped",
            completion="complete",
            reason="optional",
            detail="ariaflow web UI is optional and not installed by default",
        )
    return plan


def uninstall_all(dry_run: bool = False, include_web: bool = False) -> dict[str, dict[str, object]]:
    if not dry_run and not is_macos():
        raise RuntimeError("uninstall is only supported on macOS")
    aria2_cmds = uninstall_aria2_launchd(dry_run=dry_run)
    plan = {
        "aria2-launchd": ucc_record(
            target="aria2-launchd",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="uninstall",
            detail="aria2 launchd removed or queued for removal",
            commands=aria2_cmds,
        ),
    }
    if include_web:
        serve_cmds = uninstall_ariaflow_launchd(dry_run=dry_run)
        plan["ariaflow-serve-launchd"] = ucc_record(
            target="ariaflow-serve-launchd",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="uninstall",
            detail="ariaflow web launchd removed or queued for removal",
            commands=serve_cmds,
        )
    return plan
