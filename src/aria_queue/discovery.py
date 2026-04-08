"""Peer discovery via Bonjour/mDNS.

Browses ``_ariaflow._tcp`` on the local network, resolves peers,
polls their ``GET /api/torrents``, and auto-downloads new torrents.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

from .bonjour import _detect_backend, _dns_sd_path
from .state import record_action


# ── Peer registry ──────────────────────────────────────────────────

_peers: dict[str, dict[str, Any]] = {}
_peers_lock = threading.Lock()
_browse_proc: subprocess.Popen | None = None
_poll_thread: threading.Thread | None = None
_stop_event = threading.Event()


def list_peers() -> list[dict[str, Any]]:
    """Return a snapshot of currently known peers."""
    with _peers_lock:
        return list(_peers.values())


# ── Browse ─────────────────────────────────────────────────────────


def _parse_dns_sd_browse_line(line: str) -> tuple[str, str, bool] | None:
    """Parse a dns-sd -B output line.

    Returns (instance_name, event, is_add) or None.
    Example lines:
        Timestamp  A/R  Flags  if  Domain  Service Type  Instance Name
        12:00:00.000  Add        3  4  local.  _ariaflow._tcp.  bc's Mac mini AriaFlow
        12:00:01.000  Rmv        0  4  local.  _ariaflow._tcp.  bc's Mac mini AriaFlow
    """
    parts = line.split()
    if len(parts) < 7:
        return None
    event = parts[1]
    if event not in ("Add", "Rmv"):
        return None
    # Instance name is everything after the service type
    try:
        svc_idx = line.index("_ariaflow._tcp.")
        instance = line[svc_idx + len("_ariaflow._tcp.") :].strip()
    except ValueError:
        return None
    if not instance:
        return None
    return instance, event, event == "Add"


def _parse_avahi_browse_line(line: str) -> tuple[str, dict[str, Any]] | None:
    """Parse avahi-browse -r -p output (parseable mode).

    Returns (instance_name, peer_info) or None.
    Format: +;eth0;IPv4;instance;_ariaflow._tcp;local;host.local;192.168.1.10;8080;"path=/api" "tls=0"
    The '=' line has resolved info, '+' is add, '-' is remove.
    """
    if not line or line.startswith("Failed"):
        return None
    parts = line.split(";")
    if len(parts) < 6:
        return None
    event = parts[0]
    instance = parts[3]
    if not instance:
        return None
    if event == "-":
        return instance, {"removed": True}
    if len(parts) < 9:
        return None
    if event in ("=",):
        host = parts[6]
        try:
            port = int(parts[8])
        except (ValueError, IndexError):
            return None
        # Parse TXT records from remaining fields
        txt_raw = ";".join(parts[9:]) if len(parts) > 9 else ""
        txt = _parse_txt_records(txt_raw)
        tls = txt.get("tls", "0") == "1"
        path = txt.get("path", "/api")
        scheme = "https" if tls else "http"
        return instance, {
            "instance": instance,
            "host": host,
            "port": port,
            "path": path,
            "tls": tls,
            "base_url": f"{scheme}://{host}:{port}{path}",
            "last_seen": time.time(),
            "status": "discovered",
        }
    if event == "+":
        return instance, {
            "instance": instance,
            "status": "browsed",
            "last_seen": time.time(),
        }
    return None


def _parse_txt_records(raw: str) -> dict[str, str]:
    """Parse TXT records from avahi output or dns-sd output."""
    result: dict[str, str] = {}
    for match in re.finditer(r'"?(\w+)=([^"]*)"?', raw):
        result[match.group(1)] = match.group(2)
    return result


def _resolve_dns_sd(instance: str) -> dict[str, Any] | None:
    """Resolve a service instance via dns-sd -L (macOS/Windows).

    Returns peer info dict or None.
    """
    binary = _dns_sd_path()
    if not binary:
        return None
    try:
        proc = subprocess.Popen(
            [binary, "-L", instance, "_ariaflow._tcp", "local"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        # dns-sd -L outputs one line then keeps running; read for 3s
        output_lines: list[str] = []
        deadline = time.time() + 3
        while time.time() < deadline:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if not line:
                break
            output_lines.append(line.strip())
            # Look for the resolved line containing host and port
            if "can be reached at" in line:
                break
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    except (FileNotFoundError, PermissionError):
        return None

    # Parse: "bc's Mac mini AriaFlow can be reached at bc-mac-mini.local.:8080 (interface 4)"
    for line in output_lines:
        m = re.search(r"can be reached at\s+(\S+?):(\d+)", line)
        if m:
            host = m.group(1).rstrip(".")
            port = int(m.group(2))
            # TXT records appear on lines like: path=/api tls=0
            txt: dict[str, str] = {}
            for tline in output_lines:
                txt.update(_parse_txt_records(tline))
            tls = txt.get("tls", "0") == "1"
            path = txt.get("path", "/api")
            scheme = "https" if tls else "http"
            return {
                "instance": instance,
                "host": host,
                "port": port,
                "path": path,
                "tls": tls,
                "base_url": f"{scheme}://{host}:{port}{path}",
                "last_seen": time.time(),
                "status": "resolved",
            }
    return None


def _browse_dns_sd() -> None:
    """Long-running browse via dns-sd -B."""
    global _browse_proc
    binary = _dns_sd_path()
    if not binary:
        return
    try:
        _browse_proc = subprocess.Popen(
            [binary, "-B", "_ariaflow._tcp", "local"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, PermissionError):
        return

    while not _stop_event.is_set():
        if _browse_proc is None or _browse_proc.stdout is None:
            break
        line = _browse_proc.stdout.readline()
        if not line:
            break
        parsed = _parse_dns_sd_browse_line(line.strip())
        if parsed is None:
            continue
        instance, _event, is_add = parsed
        if is_add:
            info = _resolve_dns_sd(instance)
            if info:
                with _peers_lock:
                    _peers[instance] = info
                record_action(
                    action="peer_discovered",
                    target="system",
                    outcome="changed",
                    reason="bonjour_browse",
                    detail={"instance": instance, "base_url": info.get("base_url")},
                )
        else:
            with _peers_lock:
                removed = _peers.pop(instance, None)
            if removed:
                record_action(
                    action="peer_removed",
                    target="system",
                    outcome="changed",
                    reason="bonjour_browse",
                    detail={"instance": instance},
                )


def _browse_avahi() -> None:
    """Long-running browse via avahi-browse -r -p."""
    global _browse_proc
    binary = "avahi-browse"
    try:
        _browse_proc = subprocess.Popen(
            [binary, "-r", "-p", "_ariaflow._tcp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, PermissionError):
        return

    while not _stop_event.is_set():
        if _browse_proc is None or _browse_proc.stdout is None:
            break
        line = _browse_proc.stdout.readline()
        if not line:
            break
        parsed = _parse_avahi_browse_line(line.strip())
        if parsed is None:
            continue
        instance, info = parsed
        if info.get("removed"):
            with _peers_lock:
                removed = _peers.pop(instance, None)
            if removed:
                record_action(
                    action="peer_removed",
                    target="system",
                    outcome="changed",
                    reason="bonjour_browse",
                    detail={"instance": instance},
                )
        elif info.get("base_url"):
            with _peers_lock:
                _peers[instance] = info
            record_action(
                action="peer_discovered",
                target="system",
                outcome="changed",
                reason="bonjour_browse",
                detail={"instance": instance, "base_url": info["base_url"]},
            )


# ── Poll ───────────────────────────────────────────────────────────


def _poll_peer_torrents(peer: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch torrent list from a peer's API."""
    base_url = peer.get("base_url", "")
    if not base_url:
        return []
    url = f"{base_url}/torrents"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("torrents", data.get("items", []))
    except Exception:
        peer["status"] = "unreachable"
        return []


def _is_known_infohash(infohash: str) -> bool:
    """Check if we already have this torrent in our queue."""
    from .core import load_queue

    for item in load_queue():
        if item.get("distribute_infohash") == infohash:
            return True
        if item.get("infohash") == infohash:
            return True
    return False


def _fetch_torrent(peer: dict[str, Any], torrent: dict[str, Any]) -> bool:
    """Download a .torrent file from a peer and submit to local queue."""
    from .scheduler import check_disk_space
    from .core import add_queue_item

    disk_ok, _ = check_disk_space()
    if not disk_ok:
        return False

    torrent_url = torrent.get("url", "")
    if not torrent_url:
        return False

    # If URL is relative, build absolute from peer base_url
    if torrent_url.startswith("/"):
        base = peer.get("base_url", "")
        # Strip path from base_url to get scheme://host:port
        if base:
            from urllib.parse import urlparse

            p = urlparse(base)
            torrent_url = f"{p.scheme}://{p.netloc}{torrent_url}"

    try:
        result = add_queue_item(
            torrent_url,
            source_peer=peer.get("instance", "unknown"),
        )
        if result.get("ok") or result.get("id"):
            record_action(
                action="peer_fetch",
                target="queue_item",
                outcome="changed",
                reason="auto_download",
                detail={
                    "peer": peer.get("instance"),
                    "infohash": torrent.get("infohash"),
                    "url": torrent_url,
                },
            )
            return True
    except Exception:
        pass
    return False


def _matches_filter(torrent: dict[str, Any], pattern: str) -> bool:
    """Check if torrent matches the content filter pattern."""
    if not pattern:
        return True
    name = torrent.get("name", "") or torrent.get("url", "")
    return fnmatch.fnmatch(name, pattern)


def _matches_allowlist(peer: dict[str, Any], allowlist: str) -> bool:
    """Check if peer is in the allowlist."""
    if not allowlist:
        return True
    allowed = [s.strip() for s in allowlist.split(",") if s.strip()]
    return peer.get("instance", "") in allowed


def _poll_loop() -> None:
    """Periodically poll all known peers for new torrents."""
    while not _stop_event.is_set():
        from .contracts import pref_value

        interval = int(pref_value("peer_poll_interval_seconds", 60) or 60)
        max_downloads = int(pref_value("peer_max_auto_downloads", 5) or 5)
        content_filter = str(pref_value("peer_content_filter", "") or "")
        allowlist = str(pref_value("peer_allowlist", "") or "")

        with _peers_lock:
            peers_snapshot = list(_peers.values())

        fetched = 0
        for peer in peers_snapshot:
            if _stop_event.is_set():
                break
            if not _matches_allowlist(peer, allowlist):
                continue
            peer["last_polled"] = time.time()
            torrents = _poll_peer_torrents(peer)
            peer["torrent_count"] = len(torrents)
            for torrent in torrents:
                if _stop_event.is_set() or fetched >= max_downloads:
                    break
                infohash = torrent.get("infohash", "")
                if not infohash:
                    continue
                if _is_known_infohash(infohash):
                    continue
                if not _matches_filter(torrent, content_filter):
                    continue
                if _fetch_torrent(peer, torrent):
                    fetched += 1

        _stop_event.wait(timeout=interval)


# ── Lifecycle ──────────────────────────────────────────────────────


def start_discovery() -> bool:
    """Start peer discovery threads. Returns True if started."""
    global _poll_thread
    backend = _detect_backend()
    if backend is None:
        record_action(
            action="discovery_start",
            target="system",
            outcome="skipped",
            reason="no_mdns_backend",
        )
        return False

    _stop_event.clear()

    if backend == "avahi":
        browse_thread = threading.Thread(target=_browse_avahi, daemon=True)
    else:
        browse_thread = threading.Thread(target=_browse_dns_sd, daemon=True)
    browse_thread.start()

    _poll_thread = threading.Thread(target=_poll_loop, daemon=True)
    _poll_thread.start()

    record_action(
        action="discovery_start",
        target="system",
        outcome="changed",
        reason="started",
        detail={"backend": backend},
    )
    return True


def stop_discovery() -> None:
    """Stop peer discovery threads and browse process."""
    global _browse_proc, _poll_thread
    _stop_event.set()
    if _browse_proc is not None:
        try:
            _browse_proc.terminate()
            _browse_proc.wait(timeout=2)
        except Exception:
            try:
                _browse_proc.kill()
            except Exception:
                pass
        _browse_proc = None
    _poll_thread = None
    with _peers_lock:
        _peers.clear()
    record_action(
        action="discovery_stop",
        target="system",
        outcome="changed",
        reason="stopped",
    )
