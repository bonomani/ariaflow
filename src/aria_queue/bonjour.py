from __future__ import annotations

import platform
import shutil
import subprocess
import time
from contextlib import contextmanager
from typing import Iterator

from .state import record_action


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


def build_dns_sd_cmd(
    *, role: str, port: int, path: str, product: str, version: str
) -> list[str]:
    """Build dns-sd command (macOS / Windows)."""
    binary = _dns_sd_path() or "dns-sd"
    return [
        binary,
        "-R",
        f"ariaflow-{role}",
        "_ariaflow._tcp",
        "local",
        str(port),
        f"role={role}",
        f"path={path}",
        f"product={product}",
        f"version={version}",
        "proto=http",
    ]


def build_avahi_cmd(
    *, role: str, port: int, path: str, product: str, version: str
) -> list[str]:
    """Build avahi-publish-service command (Linux)."""
    binary = _avahi_publish_path() or "avahi-publish-service"
    return [
        binary,
        f"ariaflow-{role}",
        "_ariaflow._tcp",
        str(port),
        f"role={role}",
        f"path={path}",
        f"product={product}",
        f"version={version}",
        "proto=http",
    ]


def advertise_torrent(
    *, name: str, infohash: str, torrent_url: str,
    tracker: str, size: int, version: str,
) -> subprocess.Popen | None:
    """Register a torrent as _ariaflow-torrent._tcp. Returns process or None."""
    backend = _detect_backend()
    detail = {"name": name, "infohash": infohash, "backend": backend}
    if backend is None:
        record_action(
            action="bonjour_torrent_register", target="system",
            outcome="skipped", reason="no_mdns_backend", detail=detail,
        )
        return None
    txt_records = [
        f"name={name}",
        f"infohash={infohash}",
        f"torrent_url={torrent_url}",
        f"tracker={tracker}",
        f"size={size}",
        f"version={version}",
    ]
    if backend == "avahi":
        binary = _avahi_publish_path() or "avahi-publish-service"
        cmd = [binary, f"ariaflow-torrent-{infohash[:8]}", "_ariaflow-torrent._tcp", "0"] + txt_records
    else:
        binary = _dns_sd_path() or "dns-sd"
        cmd = [binary, "-R", f"ariaflow-torrent-{infohash[:8]}", "_ariaflow-torrent._tcp", "local", "0"] + txt_records
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, PermissionError) as exc:
        record_action(
            action="bonjour_torrent_register", target="system",
            outcome="failed", reason="binary_not_found", detail={**detail, "error": str(exc)},
        )
        return None
    time.sleep(0.2)
    if proc.poll() is not None:
        record_action(
            action="bonjour_torrent_register", target="system",
            outcome="failed", reason="process_exited_early", detail=detail,
        )
        return None
    record_action(
        action="bonjour_torrent_register", target="system",
        outcome="changed", reason="registered", detail=detail,
    )
    return proc


def stop_torrent_advertisement(proc: subprocess.Popen | None) -> None:
    """Stop a torrent Bonjour advertisement."""
    if proc is None:
        return
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
        action="bonjour_torrent_deregister", target="system",
        outcome="changed", reason="stopped",
    )


@contextmanager
def advertise_http_service(
    *, role: str, port: int, path: str, product: str, version: str
) -> Iterator[None]:
    backend = _detect_backend()
    detail = {"role": role, "port": port, "backend": backend}
    if backend is None:
        record_action(
            action="bonjour_register", target="system",
            outcome="skipped", reason="no_mdns_backend", detail=detail,
        )
        yield
        return
    kwargs = dict(role=role, port=port, path=path, product=product, version=version)
    cmd = build_avahi_cmd(**kwargs) if backend == "avahi" else build_dns_sd_cmd(**kwargs)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, PermissionError) as exc:
        record_action(
            action="bonjour_register", target="system",
            outcome="failed", reason="binary_not_found", detail={**detail, "error": str(exc)},
        )
        yield
        return
    # Check the process didn't exit immediately (daemon not running, etc.)
    time.sleep(0.2)
    if proc.poll() is not None:
        record_action(
            action="bonjour_register", target="system",
            outcome="failed", reason="process_exited_early", detail=detail,
        )
        yield
        return
    record_action(
        action="bonjour_register", target="system",
        outcome="changed", reason="registered", detail=detail,
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
            action="bonjour_deregister", target="system",
            outcome="changed", reason="stopped", detail=detail,
        )
