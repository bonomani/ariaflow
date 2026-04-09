from __future__ import annotations

import time
from typing import Any

from .storage import storage_locked


def _core() -> Any:
    from . import core

    return core


def _rpc_failure_message(action: str, exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return text
    name = exc.__class__.__name__.lower()
    if "timeout" in name:
        return f"aria2 {action} RPC timed out"
    if "connection" in name:
        return f"aria2 {action} RPC connection failed"
    return f"aria2 {action} RPC failed"


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


def discover_active_transfer(
    port: int = 6800, timeout: int = 5
) -> dict[str, Any] | None:
    core = _core()
    core.reconcile_live_queue(port=port, timeout=timeout, adopt_missing=True)
    state = core.load_state()
    if state.get("active_gid"):
        try:
            info = core.aria2_tell_status(
                state["active_gid"], port=port, timeout=timeout
            )
            queue_item = core.find_queue_item_by_gid(state["active_gid"])
            if queue_item:
                state["active_url"] = queue_item.get("url") or state.get("active_url")
                core.save_state(state)
            total = float(info.get("totalLength") or 0)
            done = float(info.get("completedLength") or 0)
            percent = round((done / total) * 100, 1) if total else 0
            return {
                "gid": state["active_gid"],
                "url": state.get("active_url")
                or (queue_item.get("url") if queue_item else None),
                "status": info.get("status"),
                "error_code": info.get("errorCode"),
                "error_message": info.get("errorMessage"),
                "download_speed": info.get("downloadSpeed"),
                "completed_length": info.get("completedLength"),
                "total_length": info.get("totalLength"),
                "files": info.get("files"),
                "percent": percent,
            }
        except Exception:
            pass

    active_infos = core.aria2_tell_active(port=port, timeout=timeout)
    ranked_infos = sorted(
        active_infos,
        key=lambda info: (
            float(info.get("completedLength") or 0)
            / max(float(info.get("totalLength") or 1), 1.0),
            float(info.get("completedLength") or 0),
            float(info.get("downloadSpeed") or 0),
        ),
        reverse=True,
    )
    for info in ranked_infos:
        gid = info.get("gid")
        if not gid:
            continue
        queue_item = core.find_queue_item_by_gid(gid)
        if queue_item is None:
            queue_item = core._queue_item_for_active_info(info, core.load_queue())
        if queue_item:
            state["active_gid"] = gid
            state["active_url"] = queue_item.get("url")
            core.save_state(state)
        total = float(info.get("totalLength") or 0)
        done = float(info.get("completedLength") or 0)
        percent = round((done / total) * 100, 1) if total else 0
        return {
            "gid": gid,
            "url": state.get("active_url")
            or (queue_item.get("url") if queue_item else None),
            "status": info.get("status"),
            "error_code": info.get("errorCode"),
            "error_message": info.get("errorMessage"),
            "download_speed": info.get("downloadSpeed"),
            "completed_length": info.get("completedLength"),
            "total_length": info.get("totalLength"),
            "files": info.get("files"),
            "percent": percent,
            "recovered": True,
        }
    return None


def active_status(port: int = 6800, timeout: int = 5) -> dict[str, Any] | None:
    return discover_active_transfer(port=port, timeout=timeout)


def pause_active_transfer(port: int = 6800) -> dict[str, Any]:
    core = _core()
    with storage_locked():
        state = core.load_state()
        queue_items = core.load_queue()
    active_jobs = core.aria2_tell_active(port=port, timeout=5)
    gids = [str(info.get("gid") or "") for info in active_jobs if info.get("gid")]
    queue_gids = [
        str(item.get("gid") or "")
        for item in queue_items
        if item.get("gid") and item.get("status") in {"active", "paused"}
    ]
    if not gids and not state.get("active_gid") and not queue_gids:
        return {"paused": False, "reason": "no_active_transfer"}
    before = {"state": state, "active": active_jobs}
    paused: list[str] = []
    errors: list[str] = []
    targets = gids or queue_gids or [str(state.get("active_gid") or "")]
    for gid in targets:
        if not gid:
            continue
        try:
            core.aria2_pause(gid, port=port, timeout=5)
            paused.append(gid)
        except Exception as exc:
            errors.append(_rpc_failure_message("pause", exc))
            continue
    with storage_locked():
        state = core.load_state()
        if paused:
            state["paused"] = True
        items = core.load_queue()
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for item in items:
            if str(item.get("gid") or "") in paused:
                item["status"] = "paused"
                item["live_status"] = "paused"
                item["paused_at"] = now
        core.save_state(state)
        core.save_queue(items)
    payload = {"paused": bool(paused), "gids": paused, "result": {"paused": paused}}
    if not paused:
        payload["reason"] = "pause_failed"
        if errors:
            payload["message"] = errors[0]
    core.record_action(
        action="pause",
        target="active_transfer",
        outcome="changed",
        reason="user_pause",
        before=before,
        after={
            "state": core.load_state(),
            "active": core.aria2_tell_active(port=port, timeout=5),
        },
        detail={"gids": paused, "result": payload},
    )
    return payload


def resume_active_transfer(port: int = 6800) -> dict[str, Any]:
    core = _core()
    with storage_locked():
        state = core.load_state()
        queue_items = core.load_queue()
    active_jobs = core.aria2_tell_active(port=port, timeout=5)
    queued_items = [
        item
        for item in queue_items
        if item.get("gid") and item.get("status") == "paused"
    ]
    gids = [str(info.get("gid") or "") for info in active_jobs if info.get("gid")]
    if not gids and not state.get("active_gid") and not queued_items:
        return {"resumed": False, "reason": "no_active_transfer"}
    before = {"state": state, "active": active_jobs}
    resumed: list[str] = []
    errors: list[str] = []
    resume_targets = (
        gids
        or [str(item.get("gid") or "") for item in queued_items if item.get("gid")]
        or [str(state.get("active_gid") or "")]
    )
    for gid in resume_targets:
        if not gid:
            continue
        try:
            core.aria2_unpause(gid, port=port, timeout=5)
            resumed.append(gid)
        except Exception as exc:
            errors.append(_rpc_failure_message("resume", exc))
            continue
    with storage_locked():
        state = core.load_state()
        state["paused"] = False
        items = core.load_queue()
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for item in items:
            if str(item.get("gid") or "") in resumed:
                item["status"] = "active"
                item["resumed_at"] = now
                item.pop("live_status", None)
        core.save_state(state)
        core.save_queue(items)
    payload = {
        "resumed": bool(resumed),
        "gids": resumed,
        "result": {"resumed": resumed},
    }
    if not resumed:
        payload["reason"] = "resume_failed"
        if errors:
            payload["message"] = errors[0]
    core.record_action(
        action="resume",
        target="active_transfer",
        outcome="changed",
        reason="user_resume",
        before=before,
        after={
            "state": core.load_state(),
            "active": core.aria2_tell_active(port=port, timeout=5),
        },
        detail={"gids": resumed, "result": payload},
    )
    return payload
