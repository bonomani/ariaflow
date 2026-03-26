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
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
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
    cap_mbps: int | None = None,
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
            value = str(pref.get("value", "pause")).strip().lower()
            if value in {"pause", "remove", "ignore"}:
                return value
    return "pause"


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
    if session_candidates is not candidates:
        if gid:
            for item in items:
                if item.get("status") in {"done", "error"}:
                    continue
                if item.get("gid") == gid:
                    return item
        if url:
            for item in items:
                if item.get("status") in {"done", "error"}:
                    continue
                if item.get("url") == url:
                    return item
    return None


def _merge_active_status(status: str | None) -> str:
    if status == "active":
        return "downloading"
    if status in {"paused", "waiting", "complete", "error"}:
        return str(status)
    return str(status or "downloading")


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
        if item.get("status") == "paused" and live_status == "active":
            item["status"] = "downloading"
            changed = True
        if live_status:
            item["live_status"] = live_status
        if state.get("session_id") and item.get("session_id") != state.get("session_id"):
            item["recovered"] = True
            item["recovery_session_id"] = state.get("session_id")
            item["recovered_at"] = now
            changed = True
            recovered += 1
        elif live_status == "active" and item.get("status") in {"paused", "queued"}:
            item["recovered"] = True
            item["recovery_session_id"] = state.get("session_id")
            item["recovered_at"] = now
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


def add_queue_item(url: str, output: str | None = None, post_action_rule: str = "pending") -> QueueItem:
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
        item = QueueItem(
            id=str(uuid4()),
            url=url,
            output=output,
            post_action_rule=post_action_rule or default_rule,
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
                "output": output,
                "post_action_rule": item.post_action_rule,
            },
        )
    try:
        deduplicate_active_transfers()
    except Exception:
        pass
    return item


def probe_bandwidth(percent: float = 0.8, floor_mbps: int = 2) -> dict[str, Any]:
    cmd = shutil.which("networkquality")
    if cmd is None:
        for candidate in ("/usr/bin/networkquality", "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkquality"):
            if Path(candidate).exists():
                cmd = candidate
                break
    if cmd:
        try:
            completed = subprocess.run([cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12)
            out = completed.stdout
            match = re.search(r"Downlink:\s+([\d.]+)\s+Mbps", out)
            if match:
                downlink = float(match.group(1))
                cap = max(floor_mbps, int(downlink * percent))
                return {"source": "networkquality", "reason": "probe_complete", "downlink_mbps": downlink, "cap_mbps": cap}
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            match = re.search(r"Downlink:\s+([\d.]+)\s+Mbps", out)
            if match:
                downlink = float(match.group(1))
                cap = max(floor_mbps, int(downlink * percent))
                return {"source": "networkquality", "reason": "probe_timeout_partial_capture", "downlink_mbps": downlink, "cap_mbps": cap, "partial": True}
            return {"source": "networkquality", "reason": "probe_timeout_no_parse", "downlink_mbps": None, "cap_mbps": floor_mbps, "partial": True}
        except Exception:
            return {"source": "networkquality", "reason": "probe_error", "downlink_mbps": None, "cap_mbps": floor_mbps}
    return {"source": "default", "reason": "probe_unavailable", "downlink_mbps": None, "cap_mbps": floor_mbps}


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
        return json.loads(resp.read().decode("utf-8"))


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


def add_download(item: dict[str, Any], cap_mbps: int, port: int = 6800) -> str:
    options = {
        "max-download-limit": f"{cap_mbps}M",
        "allow-overwrite": "true",
        "continue": "true",
    }
    uris = [item["url"]]
    result = aria_rpc("aria2.addUri", [uris, options], port=port)
    return result["result"]


def status(gid: str, port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    fields = ["status", "errorCode", "errorMessage", "downloadSpeed", "completedLength", "totalLength", "files"]
    result = aria_rpc("aria2.tellStatus", [gid, fields], port=port, timeout=timeout)
    return result["result"]


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


def set_bandwidth(cap_mbps: int, port: int = 6800, timeout: int = 5) -> None:
    aria_rpc("aria2.changeGlobalOption", [{"max-overall-download-limit": f"{cap_mbps}M"}], port=port, timeout=timeout)


def current_bandwidth(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        result = aria_rpc("aria2.getGlobalOption", port=port, timeout=timeout)["result"]
        return {
            "limit": result.get("max-overall-download-limit"),
            "dir": result.get("dir"),
            "seed-ratio": result.get("seed-ratio"),
        }
    except Exception as exc:
        return {"limit": None, "error": str(exc)}


def current_global_options(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    try:
        return aria_rpc("aria2.getGlobalOption", port=port, timeout=timeout)["result"]
    except Exception as exc:
        return {"error": str(exc)}


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
                item["status"] = "queued"
                item["live_status"] = "waiting"
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
    ensure_aria_daemon(port=port)
    try:
        deduplicate_active_transfers(port=port)
    except Exception:
        pass
    try:
        reconcile_live_queue(port=port, timeout=5, adopt_missing=True)
    except Exception:
        pass
    probe = probe_bandwidth()
    cap = int(probe["cap_mbps"])
    record_action(
        action="probe",
        target="bandwidth",
        outcome="changed" if probe.get("source") == "networkquality" else "unchanged",
        reason=probe.get("reason", probe.get("source", "default")),
        before={"cap": current_bandwidth(port=port)},
        after={"probe": probe, "cap_mbps": cap},
        detail=probe,
    )
    with storage_locked():
        state = load_state()
        state["running"] = True
        state["stop_requested"] = False
        state["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        save_state(state)

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
                continue
            remote_status = str(info.get("status") or "")
            item["gid"] = gid
            if remote_status:
                item["live_status"] = remote_status
            _apply_transfer_fields(item, info)
            if remote_status == "active":
                item["status"] = "downloading"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                running_infos.append(info)
                log_transfer_poll(gid=gid, item=item, info=info, cap_mbps=cap)
                if info.get("errorCode") and info["errorCode"] != "0":
                    cap_local = max(1, int(cap * 0.75))
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
                                item["status"] = "queued"
                                item["live_status"] = "waiting"
                                record_action(
                                    action="run",
                                    target="queue_item",
                                    outcome="changed",
                                    reason="download_resumed",
                                    before={"item": before_item},
                                    after={"item": dict(item), "gid": gid, "cap_mbps": cap},
                                    detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "cap_mbps": cap},
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
                    gid = add_download(item, cap_mbps=cap, port=port)
                    item["gid"] = gid
                    record_action(
                        action="run",
                        target="queue_item",
                        outcome="changed",
                        reason="download_started",
                        before={"item": before_item},
                        after={"item": dict(item), "gid": gid, "cap_mbps": cap},
                        detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "cap_mbps": cap},
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
