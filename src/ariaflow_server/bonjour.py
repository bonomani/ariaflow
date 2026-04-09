from __future__ import annotations

import platform
import shutil
import subprocess
import time
from contextlib import contextmanager
from typing import Iterator

from .state import record_action


def _short_hostname() -> str:
    """Return the short hostname (first label of platform.node())."""
    return (platform.node() or "unknown").split(".")[0]


def _instance_name() -> str:
    """Build a Bonjour instance name: ``{hostname}``.

    Uses the short hostname so the same machine is identified consistently
    across local/discovered views in the frontend (BG-5). The service type
    ``_ariaflow-server._tcp`` already identifies the software. Truncated to 63 bytes
    (RFC 6763 limit for instance names).
    """
    name = _short_hostname()
    encoded = name.encode("utf-8")
    if len(encoded) > 63:
        name = encoded[:63].decode("utf-8", errors="ignore")
    return name


def _dns_sd_path() -> str | None:
    return shutil.which("dns-sd") or shutil.which("dns-sd.exe")


def _avahi_publish_path() -> str | None:
    return shutil.which("avahi-publish-service")


def _detect_backend() -> str | None:
    """Detect available mDNS backend: 'dns-sd', 'avahi', or None.

    Does not check if the backend actually works — the startup
    verification in advertise_http_service handles that (polls the
    process after 0.2s, falls back to no-op if it exited).
    """
    system = platform.system()
    if system == "Darwin" and _dns_sd_path():
        return "dns-sd"
    if system == "Windows" and _dns_sd_path():
        return "dns-sd"
    if system == "Linux" and _avahi_publish_path():
        return "avahi"
    return None


def bonjour_available() -> bool:
    return _detect_backend() is not None


def build_dns_sd_cmd(*, port: int, path: str) -> list[str]:
    """Build dns-sd command (macOS / Windows)."""
    binary = _dns_sd_path() or "dns-sd"
    return [
        binary,
        "-R",
        _instance_name(),
        "_ariaflow-server._tcp",
        "local",
        str(port),
        f"path={path}",
        "tls=0",
        f"hostname={_short_hostname()}",
    ]


def build_avahi_cmd(*, port: int, path: str) -> list[str]:
    """Build avahi-publish-service command (Linux)."""
    binary = _avahi_publish_path() or "avahi-publish-service"
    return [
        binary,
        _instance_name(),
        "_ariaflow-server._tcp",
        str(port),
        f"path={path}",
        "tls=0",
        f"hostname={_short_hostname()}",
    ]


@contextmanager
def advertise_http_service(*, port: int, path: str = "/api") -> Iterator[None]:
    backend = _detect_backend()
    detail = {"port": port, "path": path, "backend": backend}
    if backend is None:
        record_action(
            action="bonjour_register",
            target="system",
            outcome="skipped",
            reason="no_mdns_backend",
            detail=detail,
        )
        yield
        return
    kwargs = dict(port=port, path=path)
    cmd = (
        build_avahi_cmd(**kwargs) if backend == "avahi" else build_dns_sd_cmd(**kwargs)
    )
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, PermissionError) as exc:
        record_action(
            action="bonjour_register",
            target="system",
            outcome="failed",
            reason="binary_not_found",
            detail={**detail, "error": str(exc)},
        )
        yield
        return
    # Check the process didn't exit immediately (daemon not running, etc.)
    time.sleep(0.2)
    if proc.poll() is not None:
        record_action(
            action="bonjour_register",
            target="system",
            outcome="failed",
            reason="process_exited_early",
            detail=detail,
        )
        yield
        return
    record_action(
        action="bonjour_register",
        target="system",
        outcome="changed",
        reason="registered",
        detail=detail,
    )
    try:
        yield
    finally:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        except Exception:
            pass
        record_action(
            action="bonjour_deregister",
            target="system",
            outcome="changed",
            reason="stopped",
            detail=detail,
        )
