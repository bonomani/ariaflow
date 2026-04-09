from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


UNIT_NAME = "ariaflow-aria2.service"


def _systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _unit_path() -> Path:
    return _systemd_user_dir() / UNIT_NAME


def _aria2_session_dir() -> Path:
    return Path.home() / ".aria2"


def _systemctl_is_active(unit: str) -> bool:
    if shutil.which("systemctl") is None:
        return False
    return (
        subprocess.call(
            ["systemctl", "--user", "is-active", "--quiet", unit],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


def systemd_aria2_status() -> dict[str, object]:
    version = None
    loaded = _systemctl_is_active(UNIT_NAME)
    if loaded:
        try:
            from ..core import aria2_get_version

            version = aria2_get_version(timeout=5)["version"]
        except Exception:
            version = None
    session_dir = _aria2_session_dir()
    return {
        "loaded": loaded,
        "unit_exists": _unit_path().exists(),
        "session_exists": (session_dir / "session.txt").exists(),
        "version": version,
    }


def _build_unit(bin_path: str, session_dir: Path, download_dir: Path) -> str:
    session_file = session_dir / "session.txt"
    return f"""\
[Unit]
Description=aria2 RPC daemon (managed by ariaflow)
After=network.target

[Service]
Type=simple
ExecStart={bin_path} \
  --enable-rpc=true \
  --rpc-listen-all=false \
  --rpc-listen-port=6800 \
  --rpc-allow-origin-all=true \
  --console-log-level=warn \
  --summary-interval=0 \
  --dir={download_dir} \
  --input-file={session_file} \
  --save-session={session_file}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def install_aria2_systemd(dry_run: bool = False) -> list[str]:
    bin_path = shutil.which("aria2c") or "aria2c"
    session_dir = _aria2_session_dir()
    download_dir = Path.home() / "Downloads"
    unit_text = _build_unit(bin_path, session_dir, download_dir)
    commands = [
        f"mkdir -p {session_dir} {download_dir} {_systemd_user_dir()}",
        f"touch {session_dir / 'session.txt'}",
        f"cat > {_unit_path()} <<'UNIT'\n{unit_text}UNIT",
        "systemctl --user daemon-reload",
        f"systemctl --user enable --now {UNIT_NAME}",
    ]
    if dry_run:
        return commands
    session_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    _systemd_user_dir().mkdir(parents=True, exist_ok=True)
    (session_dir / "session.txt").touch(exist_ok=True)
    _unit_path().write_text(unit_text, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", UNIT_NAME], check=True
    )
    return commands


def uninstall_aria2_systemd(dry_run: bool = False) -> list[str]:
    session_dir = _aria2_session_dir()
    commands = [
        f"systemctl --user disable --now {UNIT_NAME}",
        f"rm -f {_unit_path()}",
        "systemctl --user daemon-reload",
        f"rm -rf {session_dir}",
    ]
    if dry_run:
        return commands
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", UNIT_NAME], check=False
    )
    if _unit_path().exists():
        _unit_path().unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
    return commands
