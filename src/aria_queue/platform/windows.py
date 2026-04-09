from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


TASK_NAME = "ariaflow-server-aria2"


def _aria2_session_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "ariaflow-server" / ".aria2"
    return Path.home() / ".aria2"


def _schtasks_query(name: str) -> bool:
    if shutil.which("schtasks") is None:
        return False
    return (
        subprocess.call(
            ["schtasks", "/query", "/tn", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


def task_scheduler_aria2_status() -> dict[str, object]:
    version = None
    loaded = _schtasks_query(TASK_NAME)
    if loaded:
        try:
            from ..core import aria2_get_version

            version = aria2_get_version(timeout=5)["version"]
        except Exception:
            version = None
    session_dir = _aria2_session_dir()
    return {
        "loaded": loaded,
        "task_exists": loaded,
        "session_exists": (session_dir / "session.txt").exists(),
        "version": version,
    }


def install_aria2_task(dry_run: bool = False) -> list[str]:
    bin_path = shutil.which("aria2c") or "aria2c"
    session_dir = _aria2_session_dir()
    from .detect import default_downloads_dir

    download_dir = default_downloads_dir()
    session_file = session_dir / "session.txt"
    aria2_args = (
        f'"{bin_path}" --enable-rpc=true --rpc-listen-all=false'
        f" --rpc-listen-port=6800 --rpc-allow-origin-all=true"
        f" --console-log-level=warn --summary-interval=0"
        f' --dir="{download_dir}"'
        f' --input-file="{session_file}"'
        f' --save-session="{session_file}"'
    )
    commands = [
        f'mkdir "{session_dir}"',
        f'mkdir "{download_dir}"',
        f'echo. > "{session_file}"',
        f'schtasks /create /tn "{TASK_NAME}" /tr {aria2_args} /sc onlogon /f',
    ]
    if dry_run:
        return commands
    session_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    session_file.touch(exist_ok=True)
    subprocess.run(
        [
            "schtasks",
            "/create",
            "/tn",
            TASK_NAME,
            "/tr",
            aria2_args,
            "/sc",
            "onlogon",
            "/f",
        ],
        check=True,
    )
    return commands


def uninstall_aria2_task(dry_run: bool = False) -> list[str]:
    session_dir = _aria2_session_dir()
    commands = [
        f'schtasks /delete /tn "{TASK_NAME}" /f',
        f'rmdir /s /q "{session_dir}"',
    ]
    if dry_run:
        return commands
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        check=False,
    )
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
    return commands
