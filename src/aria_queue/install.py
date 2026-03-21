from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
import shutil
import subprocess
from pathlib import Path

from .platform.launchd import (
    aria2_status,
    ariaflow_status,
    install_aria2_launchd,
    install_ariaflow_launchd,
    is_macos,
    uninstall_aria2_launchd,
    uninstall_ariaflow_launchd,
)


def current_ariaflow_version() -> str:
    try:
        return package_version("ariaflow")
    except PackageNotFoundError:
        from . import __version__

        return __version__


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


def brew_is_installed(package: str) -> bool:
    brew = shutil.which("brew")
    if brew is None:
        for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
            if Path(candidate).exists():
                brew = candidate
                break
    if brew is None:
        return False
    return Path(brew).exists() and subprocess.call([brew, "list", package], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def brew_package_version(package: str) -> str | None:
    brew = shutil.which("brew")
    if brew is None:
        for candidate in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
            if Path(candidate).exists():
                brew = candidate
                break
    if brew is None:
        return None
    try:
        completed = subprocess.run(
            [brew, "list", "--versions", package],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return None
    text = completed.stdout.strip()
    if not text:
        return None
    parts = text.split()
    return parts[1] if len(parts) > 1 else None


def _find_networkquality() -> str | None:
    cmd = shutil.which("networkquality")
    if cmd is not None:
        return cmd
    for candidate in (
        "/usr/bin/networkquality",
        "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkquality",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def networkquality_status() -> dict[str, object]:
    cmd = _find_networkquality()
    if cmd is None:
        return {
            "installed": False,
            "usable": False,
            "version": None,
            "reason": "missing",
            "message": "networkquality tool not found",
        }
    try:
        completed = subprocess.run(
            [cmd],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=6,
        )
        output = completed.stdout or ""
        for line in output.splitlines():
            if line.strip().startswith("Downlink:"):
                return {
                    "installed": True,
                    "usable": True,
                    "version": None,
                    "reason": "ready",
                    "message": f"networkquality available at {cmd}; {line.strip()}",
                    "command": cmd,
                }
        return {
            "installed": True,
            "usable": False,
            "version": None,
            "reason": "no_output",
            "message": f"networkquality available at {cmd}; no downlink line parsed",
            "command": cmd,
        }
    except subprocess.TimeoutExpired:
        return {
            "installed": True,
            "usable": False,
            "version": None,
            "reason": "timeout",
            "message": f"networkquality available at {cmd}; probe timed out",
            "command": cmd,
        }
    except Exception as exc:
        return {
            "installed": True,
            "usable": False,
            "version": None,
            "reason": "error",
            "message": f"networkquality available at {cmd}; probe failed: {exc}",
            "command": cmd,
        }


def homebrew_install_ariaflow(dry_run: bool = False) -> list[str]:
    commands = [["brew", "tap", "bonomani/ariaflow"], ["brew", "install", "ariaflow"]]
    if dry_run:
        return [" ".join(cmd) for cmd in commands]
    for cmd in commands:
        subprocess.run(cmd, check=True)
    return [" ".join(cmd) for cmd in commands]


def homebrew_uninstall_ariaflow(dry_run: bool = False) -> list[str]:
    commands = [["brew", "uninstall", "ariaflow"]]
    if dry_run:
        return [" ".join(cmd) for cmd in commands]
    for cmd in commands:
        subprocess.run(cmd, check=True)
    return [" ".join(cmd) for cmd in commands]


def install_all(
    dry_run: bool = False,
    include_web: bool = False,
    include_aria2: bool = True,
) -> dict[str, dict[str, object]]:
    if not dry_run and not is_macos():
        raise RuntimeError("install is only supported on macOS")
    ariaflow_cmds = homebrew_install_ariaflow(dry_run=dry_run)
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
    if include_aria2:
        aria2_cmds = install_aria2_launchd(dry_run=dry_run)
        plan["aria2-launchd"] = ucc_record(
            target="aria2-launchd",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="install",
            detail="aria2 launchd service installed or queued for installation",
            commands=aria2_cmds,
        )
    return plan


def status_all() -> dict[str, dict[str, object]]:
    ariaflow_installed = brew_is_installed("ariaflow")
    ariaflow_version = brew_package_version("ariaflow")
    current_version = current_ariaflow_version()
    aria2_installed = brew_is_installed("aria2")
    aria2_version = brew_package_version("aria2")
    aria2 = aria2_status()
    networkquality = networkquality_status()
    serve = ariaflow_status()
    plan = {
        "ariaflow": ucc_record(
            target="ariaflow",
            observed=True,
            outcome="converged" if ariaflow_installed else "unchanged",
            completion="complete",
            reason="match" if ariaflow_installed else "missing",
            detail=(
                f"ariaflow installed {ariaflow_version or 'unknown'}; current production {current_version}; updates via Homebrew tap"
                if ariaflow_installed
                else f"ariaflow package absent; current production {current_version}; install/update via Homebrew tap"
            ),
        ),
        "aria2": ucc_record(
            target="aria2",
            observed=True,
            outcome="converged" if aria2_installed else "unchanged",
            completion="complete",
            reason="match" if aria2_installed else "missing",
            detail=(
                f"aria2 installed {aria2_version or 'unknown'}; current production {aria2.get('version') or 'unknown'}; required dependency"
                if aria2_installed
                else f"aria2 package absent; current production {aria2.get('version') or 'unknown'}; required dependency"
            ),
        ),
        "networkquality": ucc_record(
            target="networkquality",
            observed=True,
            outcome="converged" if networkquality["installed"] and networkquality["usable"] else "unchanged",
            completion="complete",
            reason=networkquality.get("reason", "unknown"),
            detail=str(networkquality.get("message") or "networkquality status unavailable"),
        ),
        "aria2-launchd": ucc_record(
            target="aria2-launchd",
            observed=True,
            outcome="converged" if aria2["loaded"] else "unchanged",
            completion="complete",
            reason="match" if aria2["loaded"] else "missing",
            detail=(
                f"aria2 launchd loaded ({aria2.get('version') or 'unknown'}); required dependency"
                if aria2["loaded"]
                else "aria2 launchd absent; required dependency"
            ),
        ),
    }
    if serve["loaded"] or serve["plist_exists"]:
        plan["ariaflow-serve-launchd"] = ucc_record(
            target="ariaflow-serve-launchd",
            observed=True,
            outcome="converged" if serve["loaded"] else "unchanged",
            completion="complete",
            reason="match" if serve["loaded"] else "missing",
            detail=(
                f"ariaflow web launchd loaded for {current_version}"
                if serve["loaded"]
                else f"ariaflow web launchd absent; current production {current_version}"
            ),
        )
    else:
        plan["ariaflow-serve-launchd"] = ucc_record(
            target="ariaflow-serve-launchd",
            observed=True,
            outcome="skipped",
            completion="complete",
            reason="optional",
            detail=f"ariaflow web UI is optional and not installed by default; current production {current_version}",
        )
    return plan


def uninstall_all(
    dry_run: bool = False,
    include_web: bool = False,
    include_aria2: bool = True,
) -> dict[str, dict[str, object]]:
    if not dry_run and not is_macos():
        raise RuntimeError("uninstall is only supported on macOS")
    plan = {
        "ariaflow": ucc_record(
            target="ariaflow",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="uninstall",
            detail="ariaflow package removed or queued for removal",
            commands=homebrew_uninstall_ariaflow(dry_run=dry_run),
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
    if include_aria2:
        aria2_cmds = uninstall_aria2_launchd(dry_run=dry_run)
        plan["aria2-launchd"] = ucc_record(
            target="aria2-launchd",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="uninstall",
            detail="aria2 launchd removed or queued for removal",
            commands=aria2_cmds,
        )
    return plan
