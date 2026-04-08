from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from typing import Any

from .storage import (
    config_dir,
    log_path,
)


def _core() -> Any:
    """Lazy import to allow patching through aria_queue.core."""
    from . import core

    return core


_BITS_PER_MEGABIT = 1_000_000.0
_BYTES_PER_MEGABIT = 125_000.0


def _aria2_speed_value(cap_bytes_per_sec: int) -> str:
    return str(max(0, int(cap_bytes_per_sec)))


def _cap_bytes_per_sec_from_mbps(
    downlink_mbps: float, percent: float, floor_mbps: int
) -> int:
    floor_bytes = int(floor_mbps * _BYTES_PER_MEGABIT)
    return max(floor_bytes, int(downlink_mbps * percent * _BYTES_PER_MEGABIT))


def _cap_mbps_from_bytes_per_sec(cap_bytes_per_sec: int) -> float:
    return round((float(cap_bytes_per_sec) * 8.0) / _BITS_PER_MEGABIT, 1)


def aria_rpc(
    method: str, params: list[Any] | None = None, port: int = 6800, timeout: int = 15
) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": "aria-queue",
        "method": method,
        "params": params or [],
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/jsonrpc",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"aria2 RPC returned non-object: {type(data).__name__}")
    if "error" in data:
        err = data["error"]
        if isinstance(err, dict):
            raise RuntimeError(
                f"aria2 RPC error {err.get('code')}: {err.get('message')}"
            )
        raise RuntimeError(f"aria2 RPC error: {err}")
    if "result" not in data:
        raise RuntimeError(f"aria2 RPC response missing 'result': {list(data.keys())}")
    return data


def _aria2_rpc(
    method: str, params: list[Any] | None = None, port: int = 6800, timeout: int = 15
) -> dict[str, Any]:
    """Call aria_rpc through core module to support patching."""
    if params is not None:
        return _core().aria_rpc(method, params, port=port, timeout=timeout)
    return _core().aria_rpc(method, [], port=port, timeout=timeout)


# ── aria2 RPC wrappers (1:1 with aria2 JSON-RPC methods) ──────────


def aria2_add_uri(
    uris: list[str],
    options: dict[str, str] | None = None,
    position: int | None = None,
    port: int = 6800,
    timeout: int = 15,
) -> str:
    params: list[Any] = [uris]
    if options is not None or position is not None:
        params.append(options or {})
    if position is not None:
        params.append(position)
    return _aria2_rpc("aria2.addUri", params, port=port, timeout=timeout)["result"]


def aria2_add_torrent(
    torrent_b64: str,
    uris: list[str] | None = None,
    options: dict[str, str] | None = None,
    position: int | None = None,
    port: int = 6800,
    timeout: int = 15,
) -> str:
    params: list[Any] = [torrent_b64, uris or []]
    if options is not None or position is not None:
        params.append(options or {})
    if position is not None:
        params.append(position)
    return _aria2_rpc("aria2.addTorrent", params, port=port, timeout=timeout)["result"]


def aria2_add_metalink(
    metalink_b64: str,
    options: dict[str, str] | None = None,
    position: int | None = None,
    port: int = 6800,
    timeout: int = 15,
) -> list[str]:
    params: list[Any] = [metalink_b64]
    if options is not None or position is not None:
        params.append(options or {})
    if position is not None:
        params.append(position)
    return _aria2_rpc("aria2.addMetalink", params, port=port, timeout=timeout)["result"]


def aria2_pause(gid: str, port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.pause", [gid], port=port, timeout=timeout)["result"]


def aria2_force_pause(gid: str, port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.forcePause", [gid], port=port, timeout=timeout)["result"]


def aria2_pause_all(port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.pauseAll", port=port, timeout=timeout)["result"]


def aria2_force_pause_all(port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.forcePauseAll", port=port, timeout=timeout)["result"]


def aria2_unpause(gid: str, port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.unpause", [gid], port=port, timeout=timeout)["result"]


def aria2_unpause_all(port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.unpauseAll", port=port, timeout=timeout)["result"]


def aria2_remove(gid: str, port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.remove", [gid], port=port, timeout=timeout)["result"]


def aria2_force_remove(gid: str, port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.forceRemove", [gid], port=port, timeout=timeout)["result"]


def aria2_remove_download_result(gid: str, port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.removeDownloadResult", [gid], port=port, timeout=timeout)[
        "result"
    ]


def aria2_tell_status(
    gid: str, fields: list[str] | None = None, port: int = 6800, timeout: int = 5
) -> dict[str, Any]:
    params: list[Any] = [gid]
    if fields is not None:
        params.append(fields)
    return _aria2_rpc("aria2.tellStatus", params, port=port, timeout=timeout)["result"]


def aria2_tell_active(port: int = 6800, timeout: int = 5) -> list[dict[str, Any]]:
    try:
        result = _aria2_rpc("aria2.tellActive", port=port, timeout=timeout)
        return list(result.get("result", []))
    except Exception:
        return []


def aria2_tell_waiting(
    port: int = 6800, offset: int = 0, num: int = 100, timeout: int = 5
) -> list[dict[str, Any]]:
    try:
        result = _aria2_rpc(
            "aria2.tellWaiting", [offset, num], port=port, timeout=timeout
        )
        return list(result.get("result", []))
    except Exception:
        return []


def aria2_tell_stopped(
    port: int = 6800, offset: int = 0, num: int = 100, timeout: int = 5
) -> list[dict[str, Any]]:
    try:
        result = _aria2_rpc(
            "aria2.tellStopped", [offset, num], port=port, timeout=timeout
        )
        return list(result.get("result", []))
    except Exception:
        return []


def aria2_get_files(
    gid: str, port: int = 6800, timeout: int = 5
) -> list[dict[str, Any]]:
    return _aria2_rpc("aria2.getFiles", [gid], port=port, timeout=timeout)["result"]


def aria2_get_uris(
    gid: str, port: int = 6800, timeout: int = 5
) -> list[dict[str, Any]]:
    return _aria2_rpc("aria2.getUris", [gid], port=port, timeout=timeout)["result"]


def aria2_get_peers(
    gid: str, port: int = 6800, timeout: int = 5
) -> list[dict[str, Any]]:
    return _aria2_rpc("aria2.getPeers", [gid], port=port, timeout=timeout)["result"]


def aria2_get_servers(
    gid: str, port: int = 6800, timeout: int = 5
) -> list[dict[str, Any]]:
    return _aria2_rpc("aria2.getServers", [gid], port=port, timeout=timeout)["result"]


def aria2_get_option(gid: str, port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    return _aria2_rpc("aria2.getOption", [gid], port=port, timeout=timeout)["result"]


def aria2_change_option(
    gid: str, options: dict[str, str], port: int = 6800, timeout: int = 5
) -> str:
    return _aria2_rpc("aria2.changeOption", [gid, options], port=port, timeout=timeout)[
        "result"
    ]


def aria2_get_global_option(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    return _aria2_rpc("aria2.getGlobalOption", port=port, timeout=timeout)["result"]


def aria2_change_global_option(
    options: dict[str, str], port: int = 6800, timeout: int = 5
) -> str:
    return _aria2_rpc(
        "aria2.changeGlobalOption", [options], port=port, timeout=timeout
    )["result"]


def aria2_get_global_stat(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    return _aria2_rpc("aria2.getGlobalStat", port=port, timeout=timeout)["result"]


def aria2_change_position(
    gid: str, pos: int, how: str, port: int = 6800, timeout: int = 5
) -> int:
    return _aria2_rpc(
        "aria2.changePosition", [gid, pos, how], port=port, timeout=timeout
    )["result"]


def aria2_change_uri(
    gid: str,
    file_index: int,
    del_uris: list[str],
    add_uris: list[str],
    position: int | None = None,
    port: int = 6800,
    timeout: int = 5,
) -> list[int]:
    params: list[Any] = [gid, file_index, del_uris, add_uris]
    if position is not None:
        params.append(position)
    return _aria2_rpc("aria2.changeUri", params, port=port, timeout=timeout)["result"]


def aria2_purge_download_result(port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.purgeDownloadResult", port=port, timeout=timeout)["result"]


def aria2_get_version(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    return _aria2_rpc("aria2.getVersion", port=port, timeout=timeout)["result"]


def aria2_get_session_info(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    return _aria2_rpc("aria2.getSessionInfo", port=port, timeout=timeout)["result"]


def aria2_save_session(port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.saveSession", port=port, timeout=timeout)["result"]


def aria2_shutdown(port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.shutdown", port=port, timeout=timeout)["result"]


def aria2_force_shutdown(port: int = 6800, timeout: int = 5) -> str:
    return _aria2_rpc("aria2.forceShutdown", port=port, timeout=timeout)["result"]


def aria2_multicall(
    calls: list[dict[str, Any]], port: int = 6800, timeout: int = 15
) -> list[Any]:
    return _aria2_rpc("system.multicall", [calls], port=port, timeout=timeout)["result"]


def aria2_list_methods(port: int = 6800, timeout: int = 5) -> list[str]:
    return _aria2_rpc("system.listMethods", port=port, timeout=timeout)["result"]


def aria2_list_notifications(port: int = 6800, timeout: int = 5) -> list[str]:
    return _aria2_rpc("system.listNotifications", port=port, timeout=timeout)["result"]


def aria2_ensure_daemon(port: int = 6800) -> None:
    try:
        aria2_get_version(port=port)
        return
    except Exception:
        pass

    session_file = config_dir() / "aria2.session"
    args = [
        "aria2c",
        "--enable-rpc=true",
        "--rpc-listen-all=false",
        f"--rpc-listen-port={port}",
        "--rpc-allow-origin-all=true",
        "--console-log-level=warn",
        "--summary-interval=0",
        f"--log={log_path()}",
        "--log-level=warn",
        f"--save-session={session_file}",
        "--save-session-interval=30",
        "--bt-force-encryption=true",
        "--dht-listen-port=0",
    ]
    if session_file.exists():
        args.append(f"--input-file={session_file}")
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise RuntimeError(
            "aria2c not found — install aria2 (brew install aria2 / apt install aria2)"
        )
    time.sleep(2)
    try:
        aria2_get_version(port=port, timeout=5)
    except Exception as exc:
        raise RuntimeError(f"aria2c failed to start on port {port}: {exc}") from exc


def _is_metadata_url(url: str) -> bool:
    lower = url.lower().rstrip("?&#")
    return (
        lower.endswith(".torrent")
        or lower.endswith(".metalink")
        or lower.endswith(".meta4")
        or lower.startswith("magnet:")
    )


def aria2_add_download(
    item: dict[str, Any], cap_bytes_per_sec: int, port: int = 6800
) -> str:
    from .contracts import pref_value as _pref_value

    max_tries = str(int(_pref_value("aria2_max_tries", 5) or 5))
    retry_wait = str(int(_pref_value("aria2_retry_wait", 10) or 10))
    options: dict[str, str] = {
        "max-download-limit": _aria2_speed_value(cap_bytes_per_sec),
        "allow-overwrite": "true",
        "continue": "true",
        "max-tries": max_tries,
        "retry-wait": retry_wait,
    }
    mode = str(item.get("mode") or "http")
    url = str(item.get("url") or "")

    if mode == "torrent_data":
        data_b64 = item.get("torrent_data") or ""
        if not data_b64:
            raise RuntimeError("torrent_data mode but no torrent_data provided")
        options["pause-metadata"] = "true"
        return aria2_add_torrent(data_b64, uris=[], options=options, port=port)

    if mode == "metalink_data":
        data_b64 = item.get("metalink_data") or ""
        if not data_b64:
            raise RuntimeError("metalink_data mode but no metalink_data provided")
        gids = aria2_add_metalink(data_b64, options=options, port=port)
        if isinstance(gids, list) and gids:
            return gids[0]
        if isinstance(gids, str) and gids:
            return gids
        raise RuntimeError("aria2.addMetalink returned no GIDs")

    if mode == "mirror":
        mirrors = item.get("mirrors") or []
        uris = list(dict.fromkeys([url] + [str(m) for m in mirrors]))
        if not uris:
            uris = [url]
        return aria2_add_uri(uris, options=options, port=port)

    if mode in ("torrent", "metalink", "magnet"):
        options["pause-metadata"] = "true"

    uris = [url]
    return aria2_add_uri(uris, options=options, port=port)


def aria2_status(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        version = aria2_get_version(port=port, timeout=timeout)["version"]
    except Exception as exc:
        return {"reachable": False, "version": None, "error": str(exc)}
    return {"reachable": True, "version": version, "error": None}


def aria2_set_max_overall_download_limit(
    cap_bytes_per_sec: int, port: int = 6800, timeout: int = 5
) -> None:
    aria2_change_global_option(
        {"max-overall-download-limit": _aria2_speed_value(cap_bytes_per_sec)},
        port=port,
        timeout=timeout,
    )


def aria2_set_max_overall_upload_limit(
    cap_bytes_per_sec: int, port: int = 6800, timeout: int = 5
) -> None:
    aria2_change_global_option(
        {"max-overall-upload-limit": _aria2_speed_value(cap_bytes_per_sec)},
        port=port,
        timeout=timeout,
    )


def aria2_set_max_download_limit(
    gid: str, cap_bytes_per_sec: int, port: int = 6800, timeout: int = 5
) -> None:
    aria2_change_option(
        gid,
        {"max-download-limit": _aria2_speed_value(cap_bytes_per_sec)},
        port=port,
        timeout=timeout,
    )


def aria2_set_max_upload_limit(
    gid: str, cap_bytes_per_sec: int, port: int = 6800, timeout: int = 5
) -> None:
    aria2_change_option(
        gid,
        {"max-upload-limit": _aria2_speed_value(cap_bytes_per_sec)},
        port=port,
        timeout=timeout,
    )


def aria2_set_seed_ratio(ratio: float, port: int = 6800, timeout: int = 5) -> None:
    aria2_change_global_option(
        {"seed-ratio": str(ratio)},
        port=port,
        timeout=timeout,
    )


def aria2_set_seed_time(minutes: int, port: int = 6800, timeout: int = 5) -> None:
    aria2_change_global_option(
        {"seed-time": str(minutes)},
        port=port,
        timeout=timeout,
    )


def aria2_current_bandwidth(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        result = aria2_get_global_option(port=port, timeout=timeout)
        payload: dict[str, Any] = {
            "limit": result.get("max-overall-download-limit"),
            "dir": result.get("dir"),
            "seed-ratio": result.get("seed-ratio"),
        }
    except Exception as exc:
        payload = {"limit": None, "error": str(exc)}
    try:
        state = _core().load_state()
    except Exception:
        state = {}
    probe = state.get("last_bandwidth_probe")
    if isinstance(probe, dict):
        for key in (
            "source",
            "reason",
            "downlink_mbps",
            "cap_mbps",
            "cap_bytes_per_sec",
            "partial",
            "command",
            "command_mode",
            "responsiveness_rpm",
            "interface_name",
            "interval_seconds",
        ):
            if key in probe:
                payload[key] = probe[key]
    if "last_bandwidth_probe_at" in state:
        payload["last_probe_at"] = state.get("last_bandwidth_probe_at")
    return payload


def aria2_current_global_options(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        return aria2_get_global_option(port=port, timeout=timeout)
    except Exception as exc:
        return {"error": str(exc)}


# Options managed by dedicated aria2_set_* functions — blocked from generic API
_MANAGED_ARIA2_OPTIONS = {
    "max-overall-download-limit",
    "max-overall-upload-limit",
    "max-download-limit",
    "max-upload-limit",
    "seed-ratio",
    "seed-time",
}

# Options allowed via generic API without unsafe mode
_SAFE_ARIA2_OPTIONS = {
    "max-concurrent-downloads",
    "max-connection-per-server",
    "split",
    "min-split-size",
    "timeout",
    "connect-timeout",
}


def aria2_change_options(options: dict[str, str], port: int = 6800) -> dict[str, Any]:
    from .contracts import pref_value as _pref_value

    core = _core()
    managed = [k for k in options if k in _MANAGED_ARIA2_OPTIONS]
    if managed:
        return {
            "ok": False,
            "error": "managed_options",
            "message": f"use dedicated aria2_set_* functions for: {managed}",
        }
    unsafe_mode = bool(_pref_value("aria2_unsafe_options", False))
    if not unsafe_mode:
        rejected = [k for k in options if k not in _SAFE_ARIA2_OPTIONS]
    else:
        rejected = []
    if rejected:
        return {
            "ok": False,
            "error": "rejected_options",
            "message": f"unsafe options (enable aria2_unsafe_options preference): {rejected}",
        }
    if not options:
        return {"ok": False, "error": "empty_options", "message": "no options provided"}
    before = core.aria2_current_global_options(port=port)
    try:
        core.aria2_change_global_option(options, port=port, timeout=5)
    except Exception as exc:
        return {"ok": False, "error": "rpc_error", "message": str(exc)}
    after = core.aria2_current_global_options(port=port)
    core.record_action(
        action="change_options",
        target="aria2",
        outcome="changed",
        reason="user_change_options",
        before={"options": before},
        after={"options": after},
        detail={"requested": options},
    )
    return {"ok": True, "applied": options, "options": after}
