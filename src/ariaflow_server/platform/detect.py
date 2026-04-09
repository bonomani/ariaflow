from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_wsl() -> bool:
    """Detect WSL1/WSL2 by checking /proc/version for 'microsoft'."""
    if not is_linux():
        return False
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        return "microsoft" in text.lower()
    except OSError:
        return False


def wsl_windows_downloads() -> Path | None:
    """Return the Windows Downloads folder as a WSL path, or None."""
    if not is_wsl():
        return None
    try:
        result = subprocess.run(
            ["wslvar", "USERPROFILE"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            win_profile = result.stdout.strip()
            wsl_result = subprocess.run(
                ["wslpath", "-u", win_profile],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if wsl_result.returncode == 0 and wsl_result.stdout.strip():
                return Path(wsl_result.stdout.strip()) / "Downloads"
    except (OSError, subprocess.TimeoutExpired):
        pass
    # Fallback: try /mnt/c/Users/$USER/Downloads
    user = os.environ.get("USER", "")
    fallback = Path(f"/mnt/c/Users/{user}/Downloads")
    if fallback.parent.exists():
        return fallback
    return None


def default_downloads_dir() -> Path:
    """Platform-aware default download directory."""
    if is_wsl():
        wsl_dir = wsl_windows_downloads()
        if wsl_dir is not None:
            return wsl_dir
    return Path.home() / "Downloads"
