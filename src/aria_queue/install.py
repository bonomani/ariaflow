from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
import shutil
import subprocess
from pathlib import Path

from .core import _find_networkquality
from .platform.detect import is_linux, is_macos, is_windows


def current_ariaflow_server_version() -> str:
    try:
        return package_version("ariaflow-server")
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
    return (
        Path(brew).exists()
        and subprocess.call(
            [brew, "list", package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


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
    return {
        "installed": True,
        "usable": True,
        "version": None,
        "reason": "ready",
        "message": f"networkquality available at {cmd}; ariaflow-server uses bounded -u -c -s probes at startup and every 180s during runs",
        "command": cmd,
    }


def homebrew_install_ariaflow_server(dry_run: bool = False) -> list[str]:
    commands = [["brew", "tap", "bonomani/ariaflow-server"], ["brew", "install", "ariaflow-server"]]
    if dry_run:
        return [" ".join(cmd) for cmd in commands]
    for cmd in commands:
        subprocess.run(cmd, check=True)
    return [" ".join(cmd) for cmd in commands]


def homebrew_uninstall_ariaflow_server(dry_run: bool = False) -> list[str]:
    commands = [["brew", "uninstall", "ariaflow-server"]]
    if dry_run:
        return [" ".join(cmd) for cmd in commands]
    for cmd in commands:
        subprocess.run(cmd, check=True)
    return [" ".join(cmd) for cmd in commands]


def _aria2_on_path() -> bool:
    return shutil.which("aria2c") is not None


def _aria2_service_status() -> dict[str, object]:
    """Return aria2 service status for the current platform."""
    if is_macos():
        from .platform.launchd import launchd_aria2_status

        return launchd_aria2_status()
    if is_windows():
        from .platform.windows import task_scheduler_aria2_status

        return task_scheduler_aria2_status()
    if is_linux():
        from .platform.linux import systemd_aria2_status

        return systemd_aria2_status()
    return {"loaded": False, "version": None}


def _aria2_install_service(dry_run: bool = False) -> tuple[str, list[str]]:
    """Install aria2 service; returns (target_name, commands)."""
    if is_macos():
        from .platform.launchd import install_aria2_launchd

        return "aria2-launchd", install_aria2_launchd(dry_run=dry_run)
    if is_windows():
        from .platform.windows import install_aria2_task

        return "aria2-task", install_aria2_task(dry_run=dry_run)
    if is_linux():
        from .platform.linux import install_aria2_systemd

        return "aria2-systemd", install_aria2_systemd(dry_run=dry_run)
    raise RuntimeError("aria2 service install not supported on this platform")


def _aria2_uninstall_service(dry_run: bool = False) -> tuple[str, list[str]]:
    """Uninstall aria2 service; returns (target_name, commands)."""
    if is_macos():
        from .platform.launchd import uninstall_aria2_launchd

        return "aria2-launchd", uninstall_aria2_launchd(dry_run=dry_run)
    if is_windows():
        from .platform.windows import uninstall_aria2_task

        return "aria2-task", uninstall_aria2_task(dry_run=dry_run)
    if is_linux():
        from .platform.linux import uninstall_aria2_systemd

        return "aria2-systemd", uninstall_aria2_systemd(dry_run=dry_run)
    raise RuntimeError("aria2 service uninstall not supported on this platform")


def install_all(
    dry_run: bool = False,
    include_aria2: bool = False,
) -> dict[str, dict[str, object]]:
    plan: dict[str, dict[str, object]] = {}
    if is_macos():
        ariaflow_cmds = homebrew_install_ariaflow_server(dry_run=dry_run)
        plan["ariaflow"] = ucc_record(
            target="ariaflow",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="install",
            detail="ariaflow-server package installed or queued for installation",
            commands=ariaflow_cmds,
        )
    else:
        plan["ariaflow"] = ucc_record(
            target="ariaflow",
            observed=True,
            outcome="unchanged",
            completion="complete",
            reason="info",
            detail="install ariaflow via: pipx install ariaflow-server",
            commands=["pipx install ariaflow-server"],
        )
    if include_aria2:
        target, cmds = _aria2_install_service(dry_run=dry_run)
        plan[target] = ucc_record(
            target=target,
            observed=True,
            outcome="changed",
            completion="complete",
            reason="install",
            detail=f"{target} service installed or queued for installation",
            commands=cmds,
        )
    return plan


def status_all() -> dict[str, dict[str, object]]:
    current_version = current_ariaflow_server_version()
    if is_macos():
        ariaflow_installed = brew_is_installed("ariaflow-server")
        ariaflow_version = brew_package_version("ariaflow-server")
        aria2_installed = brew_is_installed("aria2")
        aria2_version = brew_package_version("aria2")
    else:
        ariaflow_installed = shutil.which("ariaflow-server") is not None
        ariaflow_version = current_version if ariaflow_installed else None
        aria2_installed = _aria2_on_path()
        aria2_version = None
    aria2 = _aria2_service_status()
    networkquality = networkquality_status()
    plan: dict[str, dict[str, object]] = {
        "ariaflow": ucc_record(
            target="ariaflow",
            observed=True,
            outcome="converged" if ariaflow_installed else "unchanged",
            completion="complete",
            reason="match" if ariaflow_installed else "missing",
            detail=(
                f"ariaflow-server installed {ariaflow_version or 'unknown'}; current production {current_version}"
                if ariaflow_installed
                else f"ariaflow-server package absent; current production {current_version}; install via: pipx install ariaflow-server"
            ),
        ),
        "aria2": ucc_record(
            target="aria2",
            observed=True,
            outcome="converged" if aria2_installed else "unchanged",
            completion="complete",
            reason="match" if aria2_installed else "missing",
            detail=(
                f"aria2 installed {aria2_version or 'unknown'}; version {aria2.get('version') or 'unknown'}; runtime download dependency"
                if aria2_installed
                else f"aria2 absent; runtime download dependency"
            ),
        ),
        "networkquality": ucc_record(
            target="networkquality",
            observed=True,
            outcome="converged"
            if networkquality["installed"] and networkquality["usable"]
            else "unchanged",
            completion="complete",
            reason=networkquality.get("reason", "unknown"),
            detail=str(
                networkquality.get("message") or "networkquality status unavailable"
            ),
        ),
    }
    service_target = "aria2-launchd" if is_macos() else "aria2-systemd" if is_linux() else "aria2-task" if is_windows() else "aria2-service"
    plan[service_target] = ucc_record(
        target=service_target,
        observed=True,
        outcome="converged" if aria2["loaded"] else "unchanged",
        completion="complete",
        reason="match" if aria2["loaded"] else "missing",
        detail=(
            f"aria2 service active ({aria2.get('version') or 'unknown'}); auto-start integration"
            if aria2["loaded"]
            else "aria2 service absent; optional auto-start integration"
        ),
    )
    return plan


def uninstall_all(
    dry_run: bool = False,
    include_aria2: bool = False,
) -> dict[str, dict[str, object]]:
    plan: dict[str, dict[str, object]] = {}
    if is_macos():
        plan["ariaflow"] = ucc_record(
            target="ariaflow",
            observed=True,
            outcome="changed",
            completion="complete",
            reason="uninstall",
            detail="ariaflow-server package removed or queued for removal",
            commands=homebrew_uninstall_ariaflow_server(dry_run=dry_run),
        )
    else:
        plan["ariaflow"] = ucc_record(
            target="ariaflow",
            observed=True,
            outcome="unchanged",
            completion="complete",
            reason="info",
            detail="uninstall ariaflow via: pipx uninstall ariaflow-server",
            commands=["pipx uninstall ariaflow-server"],
        )
    if include_aria2:
        target, cmds = _aria2_uninstall_service(dry_run=dry_run)
        plan[target] = ucc_record(
            target=target,
            observed=True,
            outcome="changed",
            completion="complete",
            reason="uninstall",
            detail=f"{target} service removed or queued for removal",
            commands=cmds,
        )
    return plan
