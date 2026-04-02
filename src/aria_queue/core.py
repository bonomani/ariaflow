from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
import shutil
import subprocess
import time
import threading
import urllib.request
from dataclasses import dataclass, asdict
import fcntl
from pathlib import Path
from typing import Any
from uuid import uuid4


_STORAGE_LOCK = threading.RLock()
_STORAGE_LOCK_STATE = threading.local()
_BITS_PER_MEGABIT = 1_000_000.0
_BYTES_PER_MEGABIT = 125_000.0
_NETWORKQUALITY_MAX_RUNTIME = 8
_NETWORKQUALITY_TIMEOUT = 10
_NETWORKQUALITY_PROBE_INTERVAL = 180
_NETWORKQUALITY_CANDIDATES = (
    "/usr/bin/networkQuality",
    "/usr/bin/networkquality",
    "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkQuality",
    "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkquality",
)


def config_dir() -> Path:
    return Path(os.environ.get("ARIA_QUEUE_DIR", Path.home() / ".config" / "aria-queue"))


def queue_path() -> Path:
    return config_dir() / "queue.json"


def state_path() -> Path:
    return config_dir() / "state.json"


def log_path() -> Path:
    return config_dir() / "aria2.log"


def action_log_path() -> Path:
    return config_dir() / "actions.jsonl"


def storage_lock_path() -> Path:
    return config_dir() / ".storage.lock"


def ensure_storage() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)


@contextmanager
def storage_locked() -> Any:
    ensure_storage()
    with _STORAGE_LOCK:
        depth = getattr(_STORAGE_LOCK_STATE, "depth", 0)
        handle = getattr(_STORAGE_LOCK_STATE, "handle", None)
        if depth == 0 or handle is None:
            handle = storage_lock_path().open("a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except Exception:
                handle.close()
                raise
            _STORAGE_LOCK_STATE.handle = handle
        _STORAGE_LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            next_depth = getattr(_STORAGE_LOCK_STATE, "depth", 1) - 1
            _STORAGE_LOCK_STATE.depth = next_depth
            if next_depth == 0:
                current = getattr(_STORAGE_LOCK_STATE, "handle", None)
                if current is not None:
                    fcntl.flock(current.fileno(), fcntl.LOCK_UN)
                    current.close()
                if hasattr(_STORAGE_LOCK_STATE, "handle"):
                    delattr(_STORAGE_LOCK_STATE, "handle")
                if hasattr(_STORAGE_LOCK_STATE, "depth"):
                    delattr(_STORAGE_LOCK_STATE, "depth")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        time.sleep(0.05)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default


def write_json(path: Path, value: Any) -> None:
    ensure_storage()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except FileNotFoundError:
        return


_ACTION_LOG_MAX_LINES = 10000
_ACTION_LOG_KEEP_LINES = 5000


def _rotate_action_log() -> None:
    path = action_log_path()
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    if size < 512 * 1024:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= _ACTION_LOG_MAX_LINES:
        return
    path.write_text("\n".join(lines[-_ACTION_LOG_KEEP_LINES:]) + "\n", encoding="utf-8")


def append_action_log(entry: dict[str, Any]) -> None:
    with storage_locked():
        payload = dict(entry)
        payload.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        try:
            state = load_state()
            session_id = state.get("session_id")
        except Exception:
            state = None
            session_id = None
        if session_id:
            payload.setdefault("session_id", session_id)
            if state is not None:
                state["session_last_seen_at"] = payload["timestamp"]
                save_state(state)
        with action_log_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True) + "\n")
        _rotate_action_log()


def load_action_log(limit: int = 200) -> list[dict[str, Any]]:
    with storage_locked():
        path = action_log_path()
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        entries: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"error": "invalid_log_entry", "raw": line})
        return entries


def record_action(
    *,
    action: str,
    target: str,
    outcome: str,
    observation: str = "ok",
    reason: str = "aggregate",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "action": action,
        "target": target,
        "outcome": outcome,
        "observation": observation,
        "reason": reason,
    }
    if before is not None:
        entry["observed_before"] = before
    if after is not None:
        entry["observed_after"] = after
    if detail is not None:
        entry["detail"] = detail
    append_action_log(entry)
    return entry


def log_transfer_poll(
    *,
    gid: str,
    item: dict[str, Any],
    info: dict[str, Any],
    cap_mbps: float | None = None,
) -> None:
    record_action(
        action="poll",
        target="queue_item",
        outcome=info.get("status", "unknown"),
        reason="aria2_poll",
        before={"item": dict(item)},
        after={
            "status": info.get("status"),
            "downloadSpeed": info.get("downloadSpeed"),
            "completedLength": info.get("completedLength"),
            "totalLength": info.get("totalLength"),
            "errorCode": info.get("errorCode"),
            "errorMessage": info.get("errorMessage"),
            "cap_mbps": cap_mbps,
        },
        detail={
            "item_id": item.get("id"),
            "gid": gid,
            "url": item.get("url"),
            "downloadSpeed": info.get("downloadSpeed"),
            "completedLength": info.get("completedLength"),
            "totalLength": info.get("totalLength"),
            "status": info.get("status"),
        },
    )


def load_state() -> dict[str, Any]:
    with storage_locked():
        return read_json(
            state_path(),
            {
                "paused": False,
                "active_gid": None,
                "active_url": None,
                "running": False,
                "stop_requested": False,
                "session_id": None,
                "session_started_at": None,
                "session_last_seen_at": None,
                "session_closed_at": None,
                "session_closed_reason": None,
            },
        )


def save_state(state: dict[str, Any]) -> None:
    with storage_locked():
        write_json(state_path(), state)


def ensure_state_session() -> dict[str, Any]:
    with storage_locked():
        state = load_state()
        if not state.get("session_id") or state.get("session_closed_at"):
            state["session_id"] = str(uuid4())
            state["session_started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["session_last_seen_at"] = state["session_started_at"]
            state["session_closed_at"] = None
            state["session_closed_reason"] = None
            save_state(state)
        return state


def touch_state_session() -> dict[str, Any]:
    with storage_locked():
        state = load_state()
        if state.get("session_id"):
            state["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            save_state(state)
        return state


def close_state_session(reason: str = "closed") -> dict[str, Any]:
    with storage_locked():
        state = load_state()
        if state.get("session_id") and not state.get("session_closed_at"):
            now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["session_closed_at"] = now
            state["session_closed_reason"] = reason
            state["session_last_seen_at"] = now
            save_state(state)
        return state


def start_new_state_session(reason: str = "manual_new_session") -> dict[str, Any]:
    with storage_locked():
        close_state_session(reason=reason)
        state = load_state()
        state["session_id"] = str(uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state["session_started_at"] = now
        state["session_last_seen_at"] = now
        state["session_closed_at"] = None
        state["session_closed_reason"] = None
        save_state(state)
        return state


def start_background_process(port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        state = ensure_state_session()
        if state.get("running"):
            return {"started": False, "reason": "already_running"}

        state["stop_requested"] = False
        state["running"] = True
        state["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save_state(state)

    def _runner() -> None:
        try:
            process_queue(port=port)
        except Exception as exc:
            current = load_state()
            current["last_error"] = str(exc)
            current["running"] = False
            current["active_gid"] = None
            current["active_url"] = None
            save_state(current)
        finally:
            current = load_state()
            current["running"] = False
            current["stop_requested"] = False
            current["active_gid"] = None
            current["active_url"] = None
            save_state(current)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return {"started": True, "reason": "background"}


def stop_background_process(port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        state = load_state()
        if not state.get("running"):
            state["stop_requested"] = False
            save_state(state)
            return {"stopped": False, "reason": "not_running"}

        before = {"state": dict(state), "queue": summarize_queue(load_queue())}
        state["stop_requested"] = True
        save_state(state)

    gid = state.get("active_gid")
    if gid:
        try:
            aria_rpc("aria2.pause", [gid], port=port, timeout=5)
        except Exception:
            pass
        with storage_locked():
            items = load_queue()
            for current in items:
                if current.get("gid") == gid:
                    current["status"] = "paused"
                    current["live_status"] = "paused"
                    break
            save_queue(items)
    close_state_session(reason="stop_requested")
    after = {"state": load_state(), "queue": summarize_queue(load_queue())}
    record_action(
        action="stop",
        target="queue",
        outcome="changed",
        reason="user_stop",
        before=before,
        after=after,
        detail={"gid": gid, "paused": bool(gid)},
    )
    return {"stopped": True, "reason": "stopping"}


@dataclass
class QueueItem:
    id: str
    url: str
    output: str | None = None
    post_action_rule: str = "pending"
    status: str = "queued"
    created_at: str = ""
    gid: str | None = None
    session_id: str | None = None
    recovery_session_id: str | None = None
    recovered_at: str | None = None
    live_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def load_queue() -> list[dict[str, Any]]:
    with storage_locked():
        data = read_json(queue_path(), {"items": []})
        return list(data.get("items", []))


def summarize_queue(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(items),
        "queued": sum(1 for item in items if item.get("status") == "queued"),
        "downloading": sum(1 for item in items if item.get("status") == "downloading"),
        "paused": sum(1 for item in items if item.get("status") == "paused"),
        "done": sum(1 for item in items if item.get("status") == "done"),
        "error": sum(1 for item in items if item.get("status") == "error"),
    }


def save_queue(items: list[dict[str, Any]]) -> None:
    with storage_locked():
        write_json(queue_path(), {"items": items})


def find_queue_item_by_url(url: str) -> dict[str, Any] | None:
    for item in load_queue():
        if item.get("url") == url and item.get("status") != "error":
            return item
    return None


def find_queue_item_by_gid(gid: str) -> dict[str, Any] | None:
    for item in load_queue():
        if item.get("gid") == gid and item.get("status") != "error":
            return item
    return None


def dedup_active_transfer_action() -> str:
    from .contracts import load_declaration

    declaration = load_declaration()
    for pref in declaration.get("uic", {}).get("preferences", []):
        if pref.get("name") == "duplicate_active_transfer_action":
            value = str(pref.get("value", "remove")).strip().lower()
            if value in {"pause", "remove", "ignore"}:
                return value
    return "remove"


def max_simultaneous_downloads() -> int:
    from .contracts import load_declaration

    declaration = load_declaration()
    for pref in declaration.get("uic", {}).get("preferences", []):
        if pref.get("name") == "max_simultaneous_downloads":
            try:
                value = int(pref.get("value", 0))
            except (TypeError, ValueError):
                return 0
            return max(0, value)
    return 0


def _pref_value(name: str, default: Any = None) -> Any:
    from .contracts import load_declaration
    for pref in load_declaration().get("uic", {}).get("preferences", []):
        if pref.get("name") == name:
            return pref.get("value", default)
    return default


def bandwidth_config() -> dict[str, Any]:
    free_pct = max(0, min(100, int(_pref_value("bandwidth_free_percent", 20) or 20)))
    free_abs = max(0.0, float(_pref_value("bandwidth_free_absolute_mbps", 0) or 0))
    floor = max(1, int(_pref_value("bandwidth_floor_mbps", 2) or 2))
    interval = max(30, int(_pref_value("bandwidth_probe_interval_seconds", 180) or 180))
    return {
        "free_percent": free_pct,
        "free_absolute_mbps": free_abs,
        "floor_mbps": floor,
        "probe_interval_seconds": interval,
        "use_percent": 1.0 - (free_pct / 100.0),
    }


def bandwidth_status(port: int = 6800) -> dict[str, Any]:
    config = bandwidth_config()
    state = load_state()
    last_probe = state.get("last_bandwidth_probe")
    bw = current_bandwidth(port=port)
    result: dict[str, Any] = {
        "config": config,
        "current_limit": bw,
        "last_probe": last_probe if isinstance(last_probe, dict) else None,
        "last_probe_at": state.get("last_bandwidth_probe_at"),
    }
    if isinstance(last_probe, dict):
        result["interface"] = last_probe.get("interface_name")
        result["downlink_mbps"] = last_probe.get("downlink_mbps")
        result["uplink_mbps"] = last_probe.get("uplink_mbps")
        result["cap_mbps"] = last_probe.get("cap_mbps")
        result["cap_bytes_per_sec"] = last_probe.get("cap_bytes_per_sec")
        result["responsiveness_rpm"] = last_probe.get("responsiveness_rpm")
    return result


def manual_probe(port: int = 6800) -> dict[str, Any]:
    config = bandwidth_config()
    probe = probe_bandwidth(percent=config["use_percent"], floor_mbps=config["floor_mbps"])
    probe["interval_seconds"] = config["probe_interval_seconds"]
    state = load_state()
    state["last_bandwidth_probe"] = probe
    state["last_bandwidth_probe_at"] = time.time()
    save_state(state)
    cap = probe.get("cap_bytes_per_sec", 0)
    if cap > 0:
        try:
            set_bandwidth(cap, port=port)
        except Exception:
            pass
    record_action(
        action="probe",
        target="bandwidth",
        outcome="changed" if probe.get("source") == "networkquality" else "unchanged",
        reason="manual_probe",
        before={"config": config},
        after={"probe": probe},
        detail=probe,
    )
    return {
        "ok": True,
        "probe": probe,
        "config": config,
        "interface": probe.get("interface_name"),
        "downlink_mbps": probe.get("downlink_mbps"),
        "uplink_mbps": probe.get("uplink_mbps"),
        "cap_mbps": probe.get("cap_mbps"),
        "cap_bytes_per_sec": probe.get("cap_bytes_per_sec"),
        "responsiveness_rpm": probe.get("responsiveness_rpm"),
        "source": probe.get("source"),
    }


def _active_item_url(info: dict[str, Any]) -> str | None:
    files = info.get("files") or []
    if not files:
        return None
    first = files[0] if isinstance(files, list) and files else None
    if not isinstance(first, dict):
        return None
    uris = first.get("uris") or []
    if isinstance(uris, list):
        for uri_info in uris:
            if isinstance(uri_info, dict) and uri_info.get("uri"):
                return str(uri_info["uri"])
    if first.get("path"):
        return str(first["path"])
    return None


def _queue_item_for_active_info(info: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any] | None:
    gid = str(info.get("gid") or "")
    url = _active_item_url(info)
    session_id = load_state().get("session_id")
    candidates = [item for item in items if item.get("status") not in {"done", "error"}]
    if gid:
        for item in items:
            if item.get("gid") == gid:
                return item
    if url:
        for item in items:
            if item.get("url") == url:
                return item
        url_tail = url.split("?")[0].rstrip("/").split("/")[-1]
        if url_tail:
            for item in items:
                current = str(item.get("url") or "")
                if current and (current == url or current.split("?")[0].rstrip("/").split("/")[-1] == url_tail):
                    return item
    session_candidates = candidates
    if session_id:
        session_candidates = [item for item in candidates if not item.get("session_id") or item.get("session_id") == session_id]
        if session_candidates:
            candidates = session_candidates
    if gid:
        for item in candidates:
            if item.get("gid") == gid:
                return item
    if url:
        for item in candidates:
            if item.get("url") == url:
                return item
        url_tail = url.split("?")[0].rstrip("/").split("/")[-1]
        if url_tail:
            for item in candidates:
                current = str(item.get("url") or "")
                if current and (current == url or current.split("?")[0].rstrip("/").split("/")[-1] == url_tail):
                    return item
    return None


def _merge_active_status(status: str | None) -> str:
    if status == "active":
        return "downloading"
    if status in {"paused", "waiting", "complete", "error"}:
        return str(status)
    return str(status or "downloading")


def _queue_item_preference(item: dict[str, Any]) -> tuple[int, float, int, int]:
    status_rank = {
        "downloading": 3,
        "paused": 2,
        "queued": 1,
        "done": 0,
        "error": 0,
    }.get(str(item.get("status") or ""), 0)
    completed = _coerce_float(item.get("completedLength")) or 0.0
    has_gid = 1 if item.get("gid") else 0
    recovered = 1 if item.get("recovered") else 0
    return (status_rank, completed, has_gid, recovered)


def _merge_queue_rows(primary: dict[str, Any], candidate: dict[str, Any]) -> bool:
    changed = False
    primary_status = str(primary.get("status") or "").lower()
    for key in (
        "url",
        "output",
        "post_action_rule",
        "session_id",
        "error_code",
        "error_message",
        "live_status",
        "created_at",
    ):
        if not primary.get(key) and candidate.get(key):
            primary[key] = candidate.get(key)
            changed = True
    if primary_status not in {"done", "error"}:
        for key in ("recovery_session_id", "recovered_at"):
            if not primary.get(key) and candidate.get(key):
                primary[key] = candidate.get(key)
                changed = True
    for key in ("downloadSpeed", "completedLength", "totalLength", "files"):
        primary_val = _coerce_float(primary.get(key))
        candidate_val = _coerce_float(candidate.get(key))
        if key == "files":
            if not primary.get(key) and candidate.get(key):
                primary[key] = candidate.get(key)
                changed = True
            continue
        if candidate.get(key) is not None and (primary.get(key) is None or (candidate_val or 0.0) > (primary_val or 0.0)):
            primary[key] = candidate.get(key)
            changed = True
    if candidate.get("recovered") and not primary.get("recovered"):
        primary["recovered"] = True
        changed = True
    return changed


def _normalize_queue_row(item: dict[str, Any]) -> bool:
    changed = False
    status = str(item.get("status") or "").lower()
    live_status = str(item.get("live_status") or "").lower()
    if status == "paused" and live_status in {"active", "waiting"}:
        item["live_status"] = "paused"
        changed = True
    elif status == "error":
        if live_status != "error":
            item["live_status"] = "error"
            changed = True
    elif status == "done" and item.get("live_status") is not None:
        item.pop("live_status", None)
        changed = True
    if status in {"done", "error"}:
        for key in ("recovered", "recovered_at", "recovery_session_id"):
            if item.get(key) is not None:
                item.pop(key, None)
                changed = True
    return changed


def cleanup_queue_state() -> dict[str, Any]:
    ensure_storage()
    with storage_locked():
        items = load_queue()
        before_summary = summarize_queue(items)
        survivors: list[dict[str, Any]] = []
        changed = False
        normalized = 0

        for item in items:
            if _normalize_queue_row(item):
                changed = True
                normalized += 1
            gid = str(item.get("gid") or "")
            url = str(item.get("url") or "")
            match: dict[str, Any] | None = None
            for existing in survivors:
                existing_gid = str(existing.get("gid") or "")
                existing_url = str(existing.get("url") or "")
                same_gid = bool(gid and existing_gid and gid == existing_gid)
                same_url = bool(url and existing_url and url == existing_url)
                if same_gid or same_url:
                    match = existing
                    break

            if match is None:
                survivors.append(item)
                continue

            primary = match
            secondary = item
            if _queue_item_preference(item) > _queue_item_preference(match):
                primary = item
                secondary = match
                survivors[survivors.index(match)] = item
                changed = True
            if _merge_queue_rows(primary, secondary):
                changed = True

        if changed:
            save_queue(survivors)
            record_action(
                action="cleanup",
                target="queue",
                outcome="changed",
                reason="queue_rows_normalized",
                before={"summary": before_summary},
                after={"summary": summarize_queue(survivors)},
                detail={"removed": max(len(items) - len(survivors), 0), "normalized": normalized},
            )
        return {"changed": changed, "items": survivors, "removed": max(len(items) - len(survivors), 0), "normalized": normalized}


def reconcile_live_queue(port: int = 6800, timeout: int = 5, adopt_missing: bool = True) -> dict[str, Any]:
    ensure_storage()
    with storage_locked():
        state = ensure_state_session()
        items = load_queue()
        before_summary = summarize_queue(items)
    active_infos = active_gids(port=port, timeout=timeout)
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    changed = False
    recovered = 0

    def _collapse_duplicate_rows(primary: dict[str, Any], current_gid: str, current_url: str | None) -> None:
        nonlocal changed
        duplicate_keys = {key for key in ("downloadSpeed", "completedLength", "totalLength", "files") if primary.get(key) is not None}
        survivors: list[dict[str, Any]] = []
        for candidate in items:
            if candidate is primary:
                survivors.append(candidate)
                continue
            candidate_gid = str(candidate.get("gid") or "")
            candidate_url = str(candidate.get("url") or "")
            same_job = bool(current_gid and candidate_gid and candidate_gid == current_gid)
            same_url = bool(current_url and candidate_url and candidate_url == current_url)
            if not same_job and not same_url:
                survivors.append(candidate)
                continue
            for key in ("output", "post_action_rule", "session_id", "recovery_session_id", "recovered_at", "error_code", "error_message"):
                if not primary.get(key) and candidate.get(key):
                    primary[key] = candidate.get(key)
            if candidate.get("recovered"):
                primary["recovered"] = True
            for key in ("downloadSpeed", "completedLength", "totalLength", "files"):
                if key not in duplicate_keys and candidate.get(key) is not None:
                    primary[key] = candidate.get(key)
            changed = True
        if len(survivors) != len(items):
            items[:] = survivors

    for info in active_infos:
        gid = str(info.get("gid") or "")
        if not gid:
            continue
        url = _active_item_url(info)
        item = _queue_item_for_active_info(info, items)
        if item is None and adopt_missing:
            item = asdict(
                QueueItem(
                    id=str(uuid4()),
                    url=url or gid,
                    status=_merge_active_status(info.get("status")),
                    created_at=now,
                    gid=gid,
                    session_id=state.get("session_id"),
                    recovery_session_id=state.get("session_id"),
                    recovered_at=now,
                    live_status=str(info.get("status") or "active"),
                )
            )
            if url and item.get("url") != url:
                item["url"] = url
            items.append(item)
            changed = True
            recovered += 1
            continue
        if item is None:
            continue
        _collapse_duplicate_rows(item, gid, url)
        if item.get("gid") != gid:
            item["gid"] = gid
            changed = True
        live_status = str(info.get("status") or "")
        merged_status = _merge_active_status(live_status)
        if item.get("status") != merged_status:
            item["status"] = merged_status
            changed = True
        if url and not item.get("url"):
            item["url"] = url
            changed = True
        if url and item.get("url") != url:
            item["url"] = url
            changed = True
        if live_status:
            item["live_status"] = live_status
        if state.get("session_id") and item.get("session_id") != state.get("session_id"):
            item["recovered"] = True
            item["recovery_session_id"] = state.get("session_id")
            item["recovered_at"] = now
            item["session_id"] = state.get("session_id")
            changed = True
            recovered += 1
        elif live_status == "active" and item.get("status") in {"paused", "queued"}:
            item["recovered"] = True
            item["recovery_session_id"] = state.get("session_id")
            item["recovered_at"] = now
            item["session_id"] = state.get("session_id")
            changed = True
            recovered += 1

    if changed:
        with storage_locked():
            save_queue(items)
            record_action(
                action="reconcile",
                target="queue",
                outcome="changed",
                reason="live_state_merged",
                before={"summary": before_summary},
                after={"summary": summarize_queue(items), "recovered": recovered, "active": [str(info.get("gid") or "") for info in active_infos if info.get("gid")]},
                detail={"recovered": recovered, "active_count": len(active_infos), "adopt_missing": adopt_missing},
            )
    return {"changed": changed, "recovered": recovered, "active_count": len(active_infos), "items": items}


def deduplicate_active_transfers(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    active = active_gids(port=port, timeout=timeout)
    if len(active) < 2:
        return {"changed": False, "kept": [], "paused": []}
    action = dedup_active_transfer_action()
    if action == "ignore":
        return {"changed": False, "kept": [str(info.get("gid") or "") for info in active if info.get("gid")], "paused": []}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for info in active:
        url = _active_item_url(info) or str(info.get("gid") or "")
        if not url:
            continue
        grouped.setdefault(url, []).append(info)

    kept: list[str] = []
    paused: list[str] = []
    changed = False
    for url, jobs in grouped.items():
        if len(jobs) < 2:
            continue
        ranked = sorted(
            jobs,
            key=lambda info: (
                float(info.get("completedLength") or 0) / max(float(info.get("totalLength") or 1), 1.0),
                float(info.get("completedLength") or 0),
                float(info.get("downloadSpeed") or 0),
            ),
            reverse=True,
        )
        keeper = ranked[0]
        keeper_gid = str(keeper.get("gid") or "")
        if keeper_gid:
            kept.append(keeper_gid)
        for duplicate in ranked[1:]:
            gid = str(duplicate.get("gid") or "")
            if not gid:
                continue
            try:
                if action == "remove":
                    aria_rpc("aria2.remove", [gid], port=port, timeout=timeout)
                else:
                    aria_rpc("aria2.pause", [gid], port=port, timeout=timeout)
                paused.append(gid)
                changed = True
            except Exception:
                continue
    if changed:
        record_action(
            action="deduplicate",
            target="active_transfer",
            outcome="changed",
            reason="duplicate_active_transfer",
            before={"active": [info.get("gid") for info in active]},
            after={"kept": kept, "paused": paused, "action": action},
            detail={"kept": kept, "paused": paused, "group_count": len(grouped), "action": action},
        )
    return {"changed": changed, "kept": kept, "paused": paused, "action": action}


def add_queue_item(url: str, output: str | None = None, post_action_rule: str | None = None) -> QueueItem:
    from .contracts import load_declaration

    ensure_storage()
    with storage_locked():
        state = ensure_state_session()
        touch_state_session()
        items = load_queue()
        before = {"summary": summarize_queue(items)}
        existing = next((item for item in items if item.get("url") == url and item.get("status") != "error"), None)
        if existing is not None:
            record_action(
                action="add",
                target="queue",
                outcome="unchanged",
                reason="duplicate_url",
                before=before,
                after={"summary": summarize_queue(items), "item_id": existing.get("id")},
                detail={"item_id": existing.get("id"), "url": url, "status": existing.get("status"), "gid": existing.get("gid")},
            )
            return QueueItem(
                id=str(existing.get("id", "")),
                url=str(existing.get("url", url)),
                output=existing.get("output"),
                post_action_rule=existing.get("post_action_rule", post_action_rule),
                status=existing.get("status", "queued"),
                created_at=existing.get("created_at", ""),
                gid=existing.get("gid"),
                session_id=existing.get("session_id") or state.get("session_id"),
                error_code=existing.get("error_code"),
                error_message=existing.get("error_message"),
            )

        decl = load_declaration()
        preferences = decl.get("uic", {}).get("preferences", [])
        default_rule = next(
            (str(pref.get("value", "pending")) for pref in preferences if pref.get("name") == "post_action_rule"),
            "pending",
        )
        normalized_output = str(output).strip() if output is not None else ""
        resolved_output = normalized_output or None
        resolved_post_action_rule = str(post_action_rule).strip() if post_action_rule is not None else ""
        if not resolved_post_action_rule:
            resolved_post_action_rule = default_rule

        item = QueueItem(
            id=str(uuid4()),
            url=url,
            output=resolved_output,
            post_action_rule=resolved_post_action_rule,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            session_id=state.get("session_id"),
        )
        items.append(asdict(item))
        save_queue(items)
        record_action(
            action="add",
            target="queue",
            outcome="changed",
            reason="queue_item_created",
            before=before,
            after={"summary": summarize_queue(items), "item_id": item.id},
            detail={
                "item_id": item.id,
                "url": url,
                "output": item.output,
                "post_action_rule": item.post_action_rule,
            },
        )
    try:
        deduplicate_active_transfers()
    except Exception:
        pass
    return item


def _find_networkquality() -> str | None:
    for binary in ("networkQuality", "networkquality"):
        cmd = shutil.which(binary)
        if cmd is not None:
            return cmd
    for candidate in _NETWORKQUALITY_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _coerce_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _cap_bytes_per_sec_from_mbps(downlink_mbps: float, percent: float, floor_mbps: int) -> int:
    floor_bytes = int(floor_mbps * _BYTES_PER_MEGABIT)
    return max(floor_bytes, int(downlink_mbps * percent * _BYTES_PER_MEGABIT))


def _cap_mbps_from_bytes_per_sec(cap_bytes_per_sec: int) -> float:
    return round((float(cap_bytes_per_sec) * 8.0) / _BITS_PER_MEGABIT, 1)


def _aria_speed_value(cap_bytes_per_sec: int) -> str:
    return str(max(0, int(cap_bytes_per_sec)))


def _default_bandwidth_probe(
    *,
    floor_mbps: int,
    reason: str,
    partial: bool = False,
    command: str | None = None,
) -> dict[str, Any]:
    cap_bytes_per_sec = int(floor_mbps * _BYTES_PER_MEGABIT)
    probe = {
        "source": "default",
        "reason": reason,
        "downlink_mbps": None,
        "cap_mbps": round(float(floor_mbps), 1),
        "cap_bytes_per_sec": cap_bytes_per_sec,
    }
    if partial:
        probe["partial"] = True
    if command:
        probe["command"] = command
    return probe


def _parse_networkquality_output(output: str, *, percent: float, floor_mbps: int) -> dict[str, Any] | None:
    text = (output or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        throughput_bps = _coerce_float(payload.get("dl_throughput"))
        if throughput_bps and throughput_bps > 0:
            downlink_mbps = round(throughput_bps / _BITS_PER_MEGABIT, 1)
            cap_bytes_per_sec = _cap_bytes_per_sec_from_mbps(downlink_mbps, percent, floor_mbps)
            probe: dict[str, Any] = {
                "source": "networkquality",
                "reason": "probe_complete",
                "downlink_mbps": downlink_mbps,
                "cap_mbps": _cap_mbps_from_bytes_per_sec(cap_bytes_per_sec),
                "cap_bytes_per_sec": cap_bytes_per_sec,
            }
            ul_throughput_bps = _coerce_float(payload.get("ul_throughput"))
            if ul_throughput_bps and ul_throughput_bps > 0:
                probe["uplink_mbps"] = round(ul_throughput_bps / _BITS_PER_MEGABIT, 1)
            responsiveness = _coerce_float(payload.get("dl_responsiveness"))
            if responsiveness is None:
                responsiveness = _coerce_float(payload.get("responsiveness"))
            if responsiveness is not None:
                probe["responsiveness_rpm"] = round(responsiveness, 1)
            interface_name = payload.get("interface_name")
            if isinstance(interface_name, str) and interface_name:
                probe["interface_name"] = interface_name
            return probe
    match = re.search(r"Downlink(?:\s+capacity)?:\s+([\d.]+)\s+Mbps", text, re.IGNORECASE)
    if match:
        downlink_mbps = float(match.group(1))
        cap_bytes_per_sec = _cap_bytes_per_sec_from_mbps(downlink_mbps, percent, floor_mbps)
        return {
            "source": "networkquality",
            "reason": "probe_complete",
            "downlink_mbps": round(downlink_mbps, 1),
            "cap_mbps": _cap_mbps_from_bytes_per_sec(cap_bytes_per_sec),
            "cap_bytes_per_sec": cap_bytes_per_sec,
            "command_mode": "text_fallback",
        }
    return None


def probe_bandwidth(percent: float = 0.8, floor_mbps: int = 2) -> dict[str, Any]:
    cmd = _find_networkquality()
    if not cmd:
        return _default_bandwidth_probe(floor_mbps=floor_mbps, reason="probe_unavailable")

    probe_cmd = [cmd, "-u", "-c", "-s", "-M", str(_NETWORKQUALITY_MAX_RUNTIME)]
    command = " ".join(probe_cmd)
    try:
        completed = subprocess.run(
            probe_cmd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_NETWORKQUALITY_TIMEOUT,
        )
        parsed = _parse_networkquality_output(completed.stdout or "", percent=percent, floor_mbps=floor_mbps)
        if parsed:
            parsed["command"] = command
            return parsed
        return _default_bandwidth_probe(floor_mbps=floor_mbps, reason="probe_no_parse", command=command)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        parsed = _parse_networkquality_output(out, percent=percent, floor_mbps=floor_mbps)
        if parsed:
            parsed["reason"] = "probe_timeout_partial_capture"
            parsed["partial"] = True
            parsed["command"] = command
            return parsed
        return _default_bandwidth_probe(
            floor_mbps=floor_mbps,
            reason="probe_timeout_no_parse",
            partial=True,
            command=command,
        )
    except Exception:
        return _default_bandwidth_probe(floor_mbps=floor_mbps, reason="probe_error", command=command)


def _should_probe_bandwidth(state: dict[str, Any], now: float | None = None) -> bool:
    if now is None:
        now = time.time()
    last_probe_at = state.get("last_bandwidth_probe_at")
    try:
        last_probe_ts = float(last_probe_at)
    except (TypeError, ValueError):
        return True
    return (now - last_probe_ts) >= _NETWORKQUALITY_PROBE_INTERVAL


def _apply_bandwidth_probe(
    *,
    port: int = 6800,
    state: dict[str, Any] | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], float, int]:
    if state is None:
        state = load_state()
    config = bandwidth_config()
    interval = config["probe_interval_seconds"]
    use_pct = config["use_percent"]
    floor = config["floor_mbps"]
    free_abs = config["free_absolute_mbps"]
    now = time.time()
    probe = state.get("last_bandwidth_probe")
    needs_probe = force or not isinstance(probe, dict) or _should_probe_bandwidth(state, now=now)
    if needs_probe:
        probe = probe_bandwidth(percent=use_pct, floor_mbps=floor)
        probe["interval_seconds"] = interval
        state["last_bandwidth_probe"] = probe
        state["last_bandwidth_probe_at"] = now
    elif isinstance(probe, dict) and "interval_seconds" not in probe:
        probe = dict(probe)
        probe["interval_seconds"] = interval
        state["last_bandwidth_probe"] = probe
    cap_mbps = float(probe.get("cap_mbps") or 0) if isinstance(probe, dict) else 0.0
    cap_bytes_per_sec = int(
        (probe or {}).get("cap_bytes_per_sec")
        or _cap_bytes_per_sec_from_mbps(cap_mbps if cap_mbps > 0 else float(floor), 1.0, floor)
    )
    if free_abs > 0 and isinstance(probe, dict) and probe.get("downlink_mbps"):
        measured = float(probe["downlink_mbps"])
        abs_cap = max(0, measured - free_abs) * _BYTES_PER_MEGABIT
        cap_bytes_per_sec = min(cap_bytes_per_sec, max(int(floor * _BYTES_PER_MEGABIT), int(abs_cap)))
    if needs_probe:
        save_state(state)
        before_bandwidth = current_bandwidth(port=port)
        try:
            set_bandwidth(cap_bytes_per_sec, port=port)
        except Exception:
            pass
        record_action(
            action="probe",
            target="bandwidth",
            outcome="changed" if (probe or {}).get("source") == "networkquality" else "unchanged",
            reason=(probe or {}).get("reason", (probe or {}).get("source", "default")),
            before={"cap": before_bandwidth},
            after={"probe": probe, "cap_mbps": cap_mbps, "cap_bytes_per_sec": cap_bytes_per_sec},
            detail=probe if isinstance(probe, dict) else None,
        )
    return (probe if isinstance(probe, dict) else {}), cap_mbps, cap_bytes_per_sec


def aria_rpc(method: str, params: list[Any] | None = None, port: int = 6800, timeout: int = 15) -> dict[str, Any]:
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
        raise RuntimeError(f"aria2 RPC error {err.get('code')}: {err.get('message')}")
    return data


def ensure_aria_daemon(port: int = 6800) -> None:
    try:
        aria_rpc("aria2.getVersion", port=port)
        return
    except Exception:
        pass

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
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


def _is_metadata_url(url: str) -> bool:
    lower = url.lower().rstrip("?&#")
    return lower.endswith(".torrent") or lower.endswith(".metalink") or lower.endswith(".meta4") or lower.startswith("magnet:")


def add_download(item: dict[str, Any], cap_bytes_per_sec: int, port: int = 6800) -> str:
    options: dict[str, str] = {
        "max-download-limit": _aria_speed_value(cap_bytes_per_sec),
        "allow-overwrite": "true",
        "continue": "true",
    }
    url = str(item.get("url") or "")
    if _is_metadata_url(url):
        options["pause-metadata"] = "true"
    uris = [url]
    result = aria_rpc("aria2.addUri", [uris, options], port=port)
    return result["result"]


def status(gid: str, port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    fields = ["status", "errorCode", "errorMessage", "downloadSpeed", "completedLength", "totalLength", "files"]
    result = aria_rpc("aria2.tellStatus", [gid, fields], port=port, timeout=timeout)
    return result["result"]


def get_item_files(item_id: str, port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        _, item, _ = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        gid = str(item.get("gid") or "")
    if not gid:
        return {"ok": False, "error": "no_gid", "message": "item has no aria2 GID"}
    try:
        result = aria_rpc("aria2.getFiles", [gid], port=port, timeout=5)
        files = result.get("result", [])
    except Exception as exc:
        return {"ok": False, "error": "rpc_error", "message": str(exc)}
    return {"ok": True, "item_id": item_id, "gid": gid, "files": files}


def select_item_files(item_id: str, indices: list[int], port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        gid = str(item.get("gid") or "")
    if not gid:
        return {"ok": False, "error": "no_gid", "message": "item has no aria2 GID"}
    select_str = ",".join(str(i) for i in indices)
    try:
        aria_rpc("aria2.changeOption", [gid, {"select-file": select_str}], port=port, timeout=5)
        aria_rpc("aria2.unpause", [gid], port=port, timeout=5)
    except Exception as exc:
        return {"ok": False, "error": "rpc_error", "message": str(exc)}
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is not None:
            item["status"] = "downloading"
            item.pop("live_status", None)
            save_queue(items)
            record_action(
                action="select_files",
                target="queue_item",
                outcome="changed",
                reason="user_select_files",
                before={},
                after={"item": dict(item), "selected": indices},
                detail={"item_id": item_id, "gid": gid, "select": select_str},
            )
    return {"ok": True, "item_id": item_id, "gid": gid, "selected": indices}


def active_gids(port: int = 6800, timeout: int = 5) -> list[dict[str, Any]]:
    try:
        result = aria_rpc("aria2.tellActive", port=port, timeout=timeout)
        return list(result.get("result", []))
    except Exception:
        return []


def queued_gids(port: int = 6800, offset: int = 0, num: int = 100, timeout: int = 5) -> list[dict[str, Any]]:
    try:
        result = aria_rpc("aria2.tellWaiting", [offset, num], port=port, timeout=timeout)
        return list(result.get("result", []))
    except Exception:
        return []


def discover_active_transfer(port: int = 6800, timeout: int = 5) -> dict[str, Any] | None:
    reconcile_live_queue(port=port, timeout=timeout, adopt_missing=True)
    state = load_state()
    if state.get("active_gid"):
        try:
            info = status(state["active_gid"], port=port, timeout=timeout)
            queue_item = find_queue_item_by_gid(state["active_gid"])
            if queue_item:
                state["active_url"] = queue_item.get("url") or state.get("active_url")
                save_state(state)
            total = float(info.get("totalLength") or 0)
            done = float(info.get("completedLength") or 0)
            percent = round((done / total) * 100, 1) if total else 0
            return {
                "gid": state["active_gid"],
                "url": state.get("active_url") or (queue_item.get("url") if queue_item else None),
                "status": info.get("status"),
                "errorCode": info.get("errorCode"),
                "errorMessage": info.get("errorMessage"),
                "downloadSpeed": info.get("downloadSpeed"),
                "completedLength": info.get("completedLength"),
                "totalLength": info.get("totalLength"),
                "files": info.get("files"),
                "percent": percent,
            }
        except Exception:
            pass

    active_infos = active_gids(port=port, timeout=timeout)
    ranked_infos = sorted(
        active_infos,
        key=lambda info: (
            float(info.get("completedLength") or 0) / max(float(info.get("totalLength") or 1), 1.0),
            float(info.get("completedLength") or 0),
            float(info.get("downloadSpeed") or 0),
        ),
        reverse=True,
    )
    for info in ranked_infos:
        gid = info.get("gid")
        if not gid:
            continue
        queue_item = find_queue_item_by_gid(gid)
        if queue_item is None:
            queue_item = _queue_item_for_active_info(info, load_queue())
        if queue_item:
            state["active_gid"] = gid
            state["active_url"] = queue_item.get("url")
            save_state(state)
        total = float(info.get("totalLength") or 0)
        done = float(info.get("completedLength") or 0)
        percent = round((done / total) * 100, 1) if total else 0
        return {
            "gid": gid,
            "url": state.get("active_url") or (queue_item.get("url") if queue_item else None),
            "status": info.get("status"),
            "errorCode": info.get("errorCode"),
            "errorMessage": info.get("errorMessage"),
            "downloadSpeed": info.get("downloadSpeed"),
            "completedLength": info.get("completedLength"),
            "totalLength": info.get("totalLength"),
            "files": info.get("files"),
            "percent": percent,
            "recovered": True,
        }
    return None


def aria_status(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        version = aria_rpc("aria2.getVersion", port=port, timeout=timeout)["result"]["version"]
    except Exception as exc:
        return {"reachable": False, "version": None, "error": str(exc)}
    return {"reachable": True, "version": version, "error": None}


def active_status(port: int = 6800, timeout: int = 5) -> dict[str, Any] | None:
    return discover_active_transfer(port=port, timeout=timeout)


def set_bandwidth(cap_bytes_per_sec: int, port: int = 6800, timeout: int = 5) -> None:
    aria_rpc(
        "aria2.changeGlobalOption",
        [{"max-overall-download-limit": _aria_speed_value(cap_bytes_per_sec)}],
        port=port,
        timeout=timeout,
    )


def set_download_bandwidth(gid: str, cap_bytes_per_sec: int, port: int = 6800, timeout: int = 5) -> None:
    aria_rpc(
        "aria2.changeOption",
        [gid, {"max-download-limit": _aria_speed_value(cap_bytes_per_sec)}],
        port=port,
        timeout=timeout,
    )


def current_bandwidth(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        result = aria_rpc("aria2.getGlobalOption", port=port, timeout=timeout)["result"]
        payload: dict[str, Any] = {
            "limit": result.get("max-overall-download-limit"),
            "dir": result.get("dir"),
            "seed-ratio": result.get("seed-ratio"),
        }
    except Exception as exc:
        payload = {"limit": None, "error": str(exc)}
    try:
        state = load_state()
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


def current_global_options(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        return aria_rpc("aria2.getGlobalOption", port=port, timeout=timeout)["result"]
    except Exception as exc:
        return {"error": str(exc)}


_SAFE_ARIA2_OPTIONS = {
    "max-concurrent-downloads",
    "max-connection-per-server",
    "split",
    "min-split-size",
    "max-overall-download-limit",
    "max-download-limit",
    "timeout",
    "connect-timeout",
}


def change_aria2_options(options: dict[str, str], port: int = 6800) -> dict[str, Any]:
    rejected = [k for k in options if k not in _SAFE_ARIA2_OPTIONS]
    if rejected:
        return {"ok": False, "error": "rejected_options", "message": f"unsafe options: {rejected}"}
    if not options:
        return {"ok": False, "error": "empty_options", "message": "no options provided"}
    before = current_global_options(port=port)
    try:
        aria_rpc("aria2.changeGlobalOption", [options], port=port, timeout=5)
    except Exception as exc:
        return {"ok": False, "error": "rpc_error", "message": str(exc)}
    after = current_global_options(port=port)
    record_action(
        action="change_options",
        target="aria2",
        outcome="changed",
        reason="user_change_options",
        before={"options": before},
        after={"options": after},
        detail={"requested": options},
    )
    return {"ok": True, "applied": options, "options": after}


def pause_active_transfer(port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        state = load_state()
        queue_items = load_queue()
    active_jobs = active_gids(port=port, timeout=5)
    gids = [str(info.get("gid") or "") for info in active_jobs if info.get("gid")]
    queue_gids = [str(item.get("gid") or "") for item in queue_items if item.get("gid") and item.get("status") in {"downloading", "paused"}]
    if not gids and not state.get("active_gid") and not queue_gids:
        return {"paused": False, "reason": "no_active_transfer"}
    before = {"state": state, "active": active_jobs}
    paused: list[str] = []
    for gid in gids or queue_gids or [str(state.get("active_gid") or "")]:
        if not gid:
            continue
        try:
            aria_rpc("aria2.pause", [gid], port=port, timeout=5)
            paused.append(gid)
        except Exception:
            continue
    with storage_locked():
        state = load_state()
        state["paused"] = True
        items = load_queue()
        for item in items:
            if str(item.get("gid") or "") in paused:
                item["status"] = "paused"
                item["live_status"] = "paused"
        save_state(state)
        save_queue(items)
    payload = {"paused": bool(paused), "gids": paused, "result": {"paused": paused}}
    record_action(
        action="pause",
        target="active_transfer",
        outcome="changed",
        reason="user_pause",
        before=before,
        after={"state": load_state(), "active": active_gids(port=port, timeout=5)},
        detail={"gids": paused, "result": payload},
    )
    return payload


def resume_active_transfer(port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        state = load_state()
        queue_items = load_queue()
    active_jobs = active_gids(port=port, timeout=5)
    queued_items = [item for item in queue_items if item.get("gid") and item.get("status") == "paused"]
    gids = [str(info.get("gid") or "") for info in active_jobs if info.get("gid")]
    if not gids and not state.get("active_gid") and not queued_items:
        return {"resumed": False, "reason": "no_active_transfer"}
    before = {"state": state, "active": active_jobs}
    resumed: list[str] = []
    resume_targets = gids or [str(item.get("gid") or "") for item in queued_items if item.get("gid")] or [str(state.get("active_gid") or "")]
    for gid in resume_targets:
        if not gid:
            continue
        try:
            aria_rpc("aria2.unpause", [gid], port=port, timeout=5)
            resumed.append(gid)
        except Exception:
            continue
    with storage_locked():
        state = load_state()
        state["paused"] = False
        items = load_queue()
        for item in items:
            if str(item.get("gid") or "") in resumed:
                item["status"] = "downloading"
                item.pop("live_status", None)
        save_state(state)
        save_queue(items)
    payload = {"resumed": bool(resumed), "gids": resumed, "result": {"resumed": resumed}}
    record_action(
        action="resume",
        target="active_transfer",
        outcome="changed",
        reason="user_resume",
        before=before,
        after={"state": load_state(), "active": active_gids(port=port, timeout=5)},
        detail={"gids": resumed, "result": payload},
    )
    return payload


def _find_queue_item_by_id(item_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int]:
    items = load_queue()
    for idx, item in enumerate(items):
        if item.get("id") == item_id:
            return items, item, idx
    return items, None, -1


def pause_queue_item(item_id: str, port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        if item.get("status") not in {"queued", "downloading"}:
            return {"ok": False, "error": "invalid_state", "message": f"cannot pause item in status '{item.get('status')}'"}
        before = dict(item)
        gid = str(item.get("gid") or "")
    if gid:
        try:
            aria_rpc("aria2.pause", [gid], port=port, timeout=5)
        except Exception:
            pass
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        item["status"] = "paused"
        item["live_status"] = "paused"
        save_queue(items)
        record_action(
            action="pause",
            target="queue_item",
            outcome="changed",
            reason="user_pause_item",
            before={"item": before},
            after={"item": dict(item)},
            detail={"item_id": item_id, "gid": gid},
        )
    return {"ok": True, "item": dict(item)}


def resume_queue_item(item_id: str, port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        if item.get("status") != "paused":
            return {"ok": False, "error": "invalid_state", "message": f"cannot resume item in status '{item.get('status')}'"}
        before = dict(item)
        gid = str(item.get("gid") or "")
    rpc_ok = False
    if gid:
        try:
            aria_rpc("aria2.unpause", [gid], port=port, timeout=5)
            rpc_ok = True
        except Exception:
            pass
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        if gid and rpc_ok:
            item["status"] = "downloading"
            item.pop("live_status", None)
        else:
            item["status"] = "queued"
            if not rpc_ok:
                item["gid"] = None
            item.pop("live_status", None)
        save_queue(items)
        record_action(
            action="resume",
            target="queue_item",
            outcome="changed",
            reason="user_resume_item",
            before={"item": before},
            after={"item": dict(item)},
            detail={"item_id": item_id, "gid": gid},
        )
    return {"ok": True, "item": dict(item)}


def remove_queue_item(item_id: str, port: int = 6800) -> dict[str, Any]:
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        before = dict(item)
        gid = str(item.get("gid") or "")
        should_remove_aria2 = gid and item.get("status") in {"downloading", "queued", "paused"}
    if should_remove_aria2:
        try:
            aria_rpc("aria2.remove", [gid], port=port, timeout=5)
        except Exception:
            try:
                aria_rpc("aria2.removeDownloadResult", [gid], port=port, timeout=5)
            except Exception:
                pass
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        items.pop(idx)
        save_queue(items)
        record_action(
            action="remove",
            target="queue_item",
            outcome="changed",
            reason="user_remove_item",
            before={"item": before},
            after={"removed": True},
            detail={"item_id": item_id, "gid": gid},
        )
    return {"ok": True, "removed": True, "item": before}


def retry_queue_item(item_id: str) -> dict[str, Any]:
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {"ok": False, "error": "not_found", "message": f"item {item_id} not found"}
        if item.get("status") not in {"error", "failed", "stopped"}:
            return {"ok": False, "error": "invalid_state", "message": f"cannot retry item in status '{item.get('status')}'"}
        before = dict(item)
        item["status"] = "queued"
        item["gid"] = None
        item["error_code"] = None
        item["error_message"] = None
        item.pop("live_status", None)
        item.pop("rpc_failures", None)
        state = load_state()
        if state.get("session_id"):
            item["session_id"] = state["session_id"]
        save_queue(items)
        record_action(
            action="retry",
            target="queue_item",
            outcome="changed",
            reason="user_retry_item",
            before={"item": before},
            after={"item": dict(item)},
            detail={"item_id": item_id},
        )
    return {"ok": True, "item": dict(item)}


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_rate(bytes_per_second: int | float | None) -> str:
    if bytes_per_second is None:
        return "-"
    return f"{format_bytes(bytes_per_second)}/s"


def format_mbps(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{value} Mbps"


def post_action(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "reason": item.get("post_action_rule", "pending"),
        "detail": "post action policy not defined yet",
        "item_id": item["id"],
    }


def process_queue(port: int = 6800) -> list[dict[str, Any]]:
    ensure_storage()
    ensure_state_session()
    try:
        cleanup_queue_state()
    except Exception:
        pass
    ensure_aria_daemon(port=port)
    try:
        deduplicate_active_transfers(port=port)
    except Exception:
        pass
    try:
        reconcile_live_queue(port=port, timeout=5, adopt_missing=True)
    except Exception:
        pass
    with storage_locked():
        state = load_state()
        probe, cap_mbps, cap_bytes_per_sec = _apply_bandwidth_probe(port=port, state=state, force=True)
        items = load_queue()
        state["running"] = True
        state["stop_requested"] = False
        state["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save_state(state)
    for item in items:
        gid = str(item.get("gid") or "")
        if not gid:
            continue
        try:
            set_download_bandwidth(gid, cap_bytes_per_sec, port=port)
        except Exception:
            continue

    limit = max_simultaneous_downloads()

    def _finalize_primary_state(items_snapshot: list[dict[str, Any]], active_infos: list[dict[str, Any]]) -> None:
        current = load_state()
        current["running"] = bool(current.get("running"))
        current["paused"] = bool(current.get("paused"))
        current["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if active_infos:
            best = sorted(
                active_infos,
                key=lambda info: (
                    float(info.get("completedLength") or 0) / max(float(info.get("totalLength") or 1), 1.0),
                    float(info.get("completedLength") or 0),
                    float(info.get("downloadSpeed") or 0),
                ),
                reverse=True,
            )[0]
            current["active_gid"] = best.get("gid")
            match = _queue_item_for_active_info(best, items_snapshot)
            current["active_url"] = match.get("url") if match else _active_item_url(best)
        else:
            current["active_gid"] = None
            current["active_url"] = None
        save_state(current)

    def _apply_transfer_fields(item: dict[str, Any], info: dict[str, Any]) -> None:
        for key in ("downloadSpeed", "completedLength", "totalLength", "files"):
            if key in info:
                item[key] = info.get(key)

    def _queued_info(item: dict[str, Any], gid: str, status_name: str) -> dict[str, Any]:
        return {
            "gid": gid,
            "status": status_name,
            "completedLength": str(item.get("completedLength") or "0"),
            "totalLength": str(item.get("totalLength") or "0"),
            "downloadSpeed": str(item.get("downloadSpeed") or "0"),
            "files": [{"uris": [{"uri": item.get("url")}]}] if item.get("url") else [],
        }

    _MAX_RPC_FAILURES = 5

    def _poll_tracked_jobs(items_snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
        running_infos: list[dict[str, Any]] = []
        for item in items_snapshot:
            if item.get("status") in {"done", "error"}:
                continue
            gid = str(item.get("gid") or "")
            if not gid:
                continue
            before_item = dict(item)
            try:
                info = status(gid, port=port, timeout=5)
            except Exception:
                rpc_failures = item.get("rpc_failures", 0) + 1
                item["rpc_failures"] = rpc_failures
                if rpc_failures >= _MAX_RPC_FAILURES:
                    item["status"] = "error"
                    item["error_code"] = "rpc_unreachable"
                    item["error_message"] = f"aria2 RPC unreachable after {rpc_failures} consecutive attempts"
                    item.pop("live_status", None)
                    record_action(
                        action="error",
                        target="queue_item",
                        outcome="failed",
                        reason="rpc_unreachable",
                        before={"item": before_item},
                        after={"item": dict(item)},
                        detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "rpc_failures": rpc_failures},
                    )
                continue
            remote_status = str(info.get("status") or "")
            item["gid"] = gid
            item.pop("rpc_failures", None)
            if remote_status:
                item["live_status"] = remote_status
            _apply_transfer_fields(item, info)
            if remote_status == "active":
                item["status"] = "downloading"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                running_infos.append(info)
                log_transfer_poll(gid=gid, item=item, info=info, cap_mbps=cap_mbps)
                if info.get("errorCode") and info["errorCode"] != "0":
                    cap_local = max(int(_BYTES_PER_MEGABIT), int(cap_bytes_per_sec * 0.75))
                    set_bandwidth(cap_local, port=port)
                continue
            if remote_status == "waiting":
                item["status"] = "queued"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                running_infos.append(info)
                continue
            if remote_status == "paused":
                item["status"] = "paused"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                continue
            if remote_status == "complete":
                item["status"] = "done"
                item["error_code"] = None
                item["error_message"] = None
                item["post_action"] = post_action(item)
                record_action(
                    action="complete",
                    target="queue_item",
                    outcome="converged",
                    reason="download_complete",
                    before={"item": before_item},
                    after={"item": dict(item), "post_action": item.get("post_action")},
                    detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "result": item.get("post_action")},
                )
                continue
            if remote_status == "error":
                item["status"] = "error"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                record_action(
                    action="error",
                    target="queue_item",
                    outcome="failed",
                    reason="download_error",
                    before={"item": before_item},
                    after={"item": dict(item), "error_code": item.get("error_code"), "error_message": item.get("error_message")},
                    detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "error_code": item.get("error_code"), "error_message": item.get("error_message")},
                )
                continue
            if remote_status == "removed":
                item["status"] = "queued"
                item["gid"] = None
                item["error_code"] = None
                item["error_message"] = None
        return running_infos

    while True:
        with storage_locked():
            items = load_queue()
            state = load_state()
            if state.get("stop_requested"):
                active_infos = active_gids(port=port, timeout=5)
                for info in active_infos:
                    gid = str(info.get("gid") or "")
                    if not gid:
                        continue
                    try:
                        aria_rpc("aria2.pause", [gid], port=port, timeout=5)
                    except Exception:
                        pass
                    for item in items:
                        if str(item.get("gid") or "") == gid:
                            item["status"] = "paused"
                            item["live_status"] = "paused"
                            break
                state["running"] = False
                state["stop_requested"] = False
                state["paused"] = False
                state["active_gid"] = None
                state["active_url"] = None
                save_state(state)
                save_queue(items)
                close_state_session(reason="stop_requested")
                return items

            running_infos = _poll_tracked_jobs(items)
            _finalize_primary_state(items, running_infos)

            state = load_state()
            probe, cap_mbps, cap_bytes_per_sec = _apply_bandwidth_probe(port=port, state=state)
            state = load_state()
            occupied = len(running_infos)
            current_running_infos = list(running_infos)
            if not state.get("paused"):
                slots = None if limit == 0 else max(limit - occupied, 0)
                allocated = 0
                for item in items:
                    if item.get("status") not in {"queued", "paused"}:
                        continue
                    if slots is not None and allocated >= slots:
                        break
                    gid = str(item.get("gid") or "")
                    live_status = str(item.get("live_status") or "")
                    if gid:
                        if live_status in {"active", "waiting"}:
                            continue
                        if item.get("status") == "paused":
                            before_item = dict(item)
                            try:
                                aria_rpc("aria2.unpause", [gid], port=port, timeout=5)
                                try:
                                    set_download_bandwidth(gid, cap_bytes_per_sec, port=port, timeout=5)
                                except Exception:
                                    pass
                                item["status"] = "queued"
                                item["live_status"] = "waiting"
                                record_action(
                                    action="run",
                                    target="queue_item",
                                    outcome="changed",
                                    reason="download_resumed",
                                    before={"item": before_item},
                                    after={"item": dict(item), "gid": gid, "cap_mbps": cap_mbps},
                                    detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "cap_mbps": cap_mbps},
                                )
                                current_running_infos.append(_queued_info(item, gid, "waiting"))
                                allocated += 1
                                continue
                            except Exception:
                                item["gid"] = None
                                item.pop("live_status", None)
                    before_item = dict(item)
                    item["status"] = "downloading"
                    item.pop("live_status", None)
                    gid = add_download(item, cap_bytes_per_sec=cap_bytes_per_sec, port=port)
                    item["gid"] = gid
                    record_action(
                        action="run",
                        target="queue_item",
                        outcome="changed",
                        reason="download_started",
                        before={"item": before_item},
                        after={"item": dict(item), "gid": gid, "cap_mbps": cap_mbps},
                        detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "cap_mbps": cap_mbps},
                    )
                    current_running_infos.append(_queued_info(item, gid, "waiting"))
                    allocated += 1
            save_queue(items)
            _finalize_primary_state(items, current_running_infos)

            if not any(item.get("status") in {"queued", "downloading", "paused"} for item in items):
                current = load_state()
                current["running"] = False
                current["stop_requested"] = False
                current["active_gid"] = None
                current["active_url"] = None
                save_state(current)
                save_queue(items)
                close_state_session(reason="queue_complete")
                return items

        time.sleep(2)


def auto_preflight_on_run() -> bool:
    from .contracts import load_declaration

    declaration = load_declaration()
    for pref in declaration.get("uic", {}).get("preferences", []):
        if pref.get("name") == "auto_preflight_on_run":
            return bool(pref.get("value", False))
    return False


def get_active_progress(port: int = 6800) -> dict[str, Any] | None:
    state = load_state()
    gid = state.get("active_gid")
    if not gid:
        return None
    try:
        info = status(gid, port=port)
    except Exception as exc:
        return {"gid": gid, "error": str(exc), "url": state.get("active_url")}

    total = int(info.get("totalLength") or 0)
    completed = int(info.get("completedLength") or 0)
    speed = int(info.get("downloadSpeed") or 0)
    percent = round((completed / total) * 100, 2) if total else None
    return {
        "gid": gid,
        "url": state.get("active_url"),
        "status": info.get("status"),
        "download_speed": speed,
        "completed_length": completed,
        "total_length": total,
        "percent": percent,
        "error_code": info.get("errorCode"),
        "error_message": info.get("errorMessage"),
    }
