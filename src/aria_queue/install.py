from __future__ import annotations

import shutil
import subprocess

from .platform.launchd import (
    aria2_status,
    ariaflow_status,
    install_aria2_launchd,
    install_ariaflow_launchd,
    is_macos,
    uninstall_aria2_launchd,
    uninstall_ariaflow_launchd,
)


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
    return shutil.which("brew") is not None and subprocess.call(["brew", "list", package], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


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
