from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Any
from uuid import uuid4

from .storage import (
    storage_locked,
    ensure_storage,
    read_json,
    write_json,
    queue_path,
)


def _core() -> Any:
    """Lazy import to allow patching through aria_queue.core."""
    from . import core
    return core


# Valid queue item statuses:
#   discovering  — auto-detecting download mode (trying protocols)
#   queued       — ready for scheduling (fallback when aria2 unreachable)
#   waiting      — submitted to aria2, waiting for download slot
#   active       — active transfer in progress (aria2 "active")
#   paused       — transfer suspended by user or af-scheduler
#   complete     — transfer completed successfully (aria2 "complete")
#   error        — transfer failed (retryable)
#   stopped      — stopped by af-scheduler shutdown
#   cancelled    — cancelled by user (archived)
ITEM_STATUSES = {
    "discovering",
    "queued",
    "waiting",
    "active",
    "paused",
    "complete",
    "error",
    "stopped",
    "cancelled",
}

# Download modes:
#   http       — HTTP/HTTPS/FTP (aria2.addUri)
#   magnet     — magnet link (aria2.addUri)
#   torrent    — .torrent URL, pauses for file selection (aria2.addUri + pause-metadata)
#   metalink   — .metalink/.meta4 URL, pauses for file selection (aria2.addUri + pause-metadata)
#   mirror     — multiple URLs for same file (aria2.addUri([url1, url2, ...]))
#   torrent_data — direct .torrent file upload (aria2.addTorrent(base64))
#   metalink_data — direct metalink XML upload (aria2.addMetalink(base64))
_TERMINAL_STATUSES = {"complete", "error", "stopped", "cancelled"}


@dataclass
class QueueItem:
    id: str
    url: str
    output: str | None = None
    post_action_rule: str = "pending"
    status: str = "queued"
    priority: int = 0
    mode: str = "http"
    mirrors: list[str] | None = None
    torrent_data: str | None = None
    metalink_data: str | None = None
    created_at: str = ""
    gid: str | None = None
    session_id: str | None = None
    recovery_session_id: str | None = None
    recovered_at: str | None = None
    live_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    paused_at: str | None = None
    resumed_at: str | None = None
    completed_at: str | None = None
    error_at: str | None = None
    removed_at: str | None = None
    cancelled_at: str | None = None
    session_history: list[dict[str, str]] | None = None


def detect_download_mode(
    url: str,
    mirrors: list[str] | None = None,
    torrent_data: str | None = None,
    metalink_data: str | None = None,
) -> str:
    if torrent_data:
        return "torrent_data"
    if metalink_data:
        return "metalink_data"
    if mirrors and len(mirrors) > 1:
        return "mirror"
    lower = url.lower().rstrip("?&#")
    if lower.startswith("magnet:"):
        return "magnet"
    if lower.endswith(".torrent"):
        return "torrent"
    if lower.endswith(".metalink") or lower.endswith(".meta4"):
        return "metalink"
    return "http"


def load_queue() -> list[dict[str, Any]]:
    with storage_locked():
        data = read_json(queue_path(), {"items": []})
        return list(data.get("items", []))


def summarize_queue(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {"total": len(items)}
    for status in ITEM_STATUSES:
        counts[status] = sum(1 for item in items if item.get("status") == status)
    return counts


def save_queue(items: list[dict[str, Any]]) -> None:
    with storage_locked():
        write_json(queue_path(), {"items": items})



def _aria2_position_for_priority(priority: int, port: int = 6800) -> int:
    core = _core()
    waiting = core.aria2_tell_waiting(port=port)
    items_by_gid: dict[str, dict[str, Any]] = {}
    for item in core.load_queue():
        g = item.get("gid")
        if g:
            items_by_gid[g] = item
    for i, info in enumerate(waiting):
        match = items_by_gid.get(str(info.get("gid") or ""))
        if match and int(match.get("priority", 0)) < priority:
            return i
    return len(waiting)


def _aria2_apply_priority(gid: str, priority: int, port: int = 6800) -> None:
    if priority <= 0:
        return
    try:
        pos = _aria2_position_for_priority(priority, port=port)
        _core().aria2_change_position(gid, pos, "POS_SET", port=port)
    except Exception:
        pass


def find_queue_item_by_gid(gid: str) -> dict[str, Any] | None:
    for item in _core().load_queue():
        if item.get("gid") == gid and item.get("status") not in _TERMINAL_STATUSES:
            return item
    return None


def _find_queue_item_by_id(
    item_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int]:
    items = _core().load_queue()
    for idx, item in enumerate(items):
        if item.get("id") == item_id:
            return items, item, idx
    return items, None, -1


def add_queue_item(
    url: str,
    output: str | None = None,
    post_action_rule: str | None = None,
    mirrors: list[str] | None = None,
    torrent_data: str | None = None,
    metalink_data: str | None = None,
    priority: int = 0,
) -> QueueItem:
    from .contracts import load_declaration

    core = _core()
    ensure_storage()
    with storage_locked():
        state = core.ensure_state_session()
        core.touch_state_session()
        items = core.load_queue()
        before = {"summary": core.summarize_queue(items)}
        existing = next(
            (
                item
                for item in items
                if item.get("url") == url
                and item.get("status") not in _TERMINAL_STATUSES
            ),
            None,
        )
        if existing is not None:
            core.record_action(
                action="add",
                target="queue",
                outcome="unchanged",
                reason="duplicate_url",
                before=before,
                after={
                    "summary": core.summarize_queue(items),
                    "item_id": existing.get("id"),
                },
                detail={
                    "item_id": existing.get("id"),
                    "url": url,
                    "status": existing.get("status"),
                    "gid": existing.get("gid"),
                },
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
            (
                str(pref.get("value", "pending"))
                for pref in preferences
                if pref.get("name") == "post_action_rule"
            ),
            "pending",
        )
        normalized_output = str(output).strip() if output is not None else ""
        resolved_output = normalized_output or None
        resolved_post_action_rule = (
            str(post_action_rule).strip() if post_action_rule is not None else ""
        )
        if not resolved_post_action_rule:
            resolved_post_action_rule = default_rule

        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        sid = state.get("session_id")
        mode = detect_download_mode(
            url,
            mirrors=mirrors,
            torrent_data=torrent_data,
            metalink_data=metalink_data,
        )
        # discovering → queued: mode detection is synchronous
        resolved_status = "queued"
        item = QueueItem(
            id=str(uuid4()),
            url=url,
            output=resolved_output,
            post_action_rule=resolved_post_action_rule,
            status=resolved_status,
            priority=priority,
            mode=mode,
            mirrors=mirrors,
            torrent_data=torrent_data,
            metalink_data=metalink_data,
            created_at=now,
            session_id=sid,
            session_history=[{"session_id": sid, "joined_at": now, "reason": "created"}]
            if sid
            else None,
        )
        items.append(asdict(item))
        core.save_queue(items)
        core.record_action(
            action="add",
            target="queue",
            outcome="changed",
            reason="queue_item_created",
            before=before,
            after={"summary": core.summarize_queue(items), "item_id": item.id},
            detail={
                "item_id": item.id,
                "url": url,
                "output": item.output,
                "post_action_rule": item.post_action_rule,
            },
        )
    try:
        core.deduplicate_active_transfers()
    except Exception:
        pass
    if state.get("running"):
        probe = state.get("last_bandwidth_probe") or {}
        cap = int(probe.get("cap_bytes_per_sec", 0))
        try:
            gid = core.aria2_add_download(asdict(item), cap_bytes_per_sec=cap)
        except Exception:
            gid = None
        if gid:
            with storage_locked():
                live_items = core.load_queue()
                for it in live_items:
                    if it.get("id") == item.id:
                        it["gid"] = gid
                        it["status"] = "active"
                        break
                core.save_queue(live_items)
            _aria2_apply_priority(gid, priority)
            item = QueueItem(**{**asdict(item), "gid": gid, "status": "active"})
    return item


def get_item_files(item_id: str, port: int = 6800) -> dict[str, Any]:
    core = _core()
    with storage_locked():
        _, item, _ = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        gid = item.get("gid") or None
    if not gid:
        return {"ok": False, "error": "no_gid", "message": "item has no aria2 GID"}
    try:
        files = core.aria2_get_files(gid, port=port, timeout=5)
    except Exception as exc:
        return {"ok": False, "error": "rpc_error", "message": str(exc)}
    return {"ok": True, "item_id": item_id, "gid": gid, "files": files}


def select_item_files(
    item_id: str, indices: list[int], port: int = 6800
) -> dict[str, Any]:
    core = _core()
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        gid = item.get("gid") or None
    if not gid:
        return {"ok": False, "error": "no_gid", "message": "item has no aria2 GID"}
    select_str = ",".join(str(i) for i in indices)
    try:
        core.aria2_change_option(gid, {"select-file": select_str}, port=port, timeout=5)
        core.aria2_unpause(gid, port=port, timeout=5)
    except Exception as exc:
        return {"ok": False, "error": "rpc_error", "message": str(exc)}
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is not None:
            item["status"] = "active"
            item.pop("live_status", None)
            core.save_queue(items)
            core.record_action(
                action="select_files",
                target="queue_item",
                outcome="changed",
                reason="user_select_files",
                before={},
                after={"item": dict(item), "selected": indices},
                detail={"item_id": item_id, "gid": gid, "select": select_str},
            )
    return {"ok": True, "item_id": item_id, "gid": gid, "selected": indices}


def pause_queue_item(item_id: str, port: int = 6800) -> dict[str, Any]:
    core = _core()
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        if item.get("status") not in {"queued", "active"}:
            return {
                "ok": False,
                "error": "invalid_state",
                "message": f"cannot pause item in status '{item.get('status')}'",
            }
        before = dict(item)
        gid = item.get("gid") or None
    if gid:
        try:
            core.aria2_pause(gid, port=port, timeout=5)
        except Exception:
            pass
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        item["status"] = "paused"
        item["live_status"] = "paused"
        item["paused_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        core.save_queue(items)
        core.record_action(
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
    core = _core()
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        if item.get("status") != "paused":
            return {
                "ok": False,
                "error": "invalid_state",
                "message": f"cannot resume item in status '{item.get('status')}'",
            }
        before = dict(item)
        gid = item.get("gid") or None
    rpc_ok = False
    if gid:
        try:
            core.aria2_unpause(gid, port=port, timeout=5)
            rpc_ok = True
        except Exception:
            pass
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        if gid and rpc_ok:
            item["status"] = "active"
            item.pop("live_status", None)
        else:
            item["status"] = "queued"
            if not rpc_ok:
                item["gid"] = None
            item.pop("live_status", None)
        item["resumed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        core.save_queue(items)
        core.record_action(
            action="resume",
            target="queue_item",
            outcome="changed",
            reason="user_resume_item",
            before={"item": before},
            after={"item": dict(item)},
            detail={"item_id": item_id, "gid": gid},
        )
    if not rpc_ok:
        state = core.load_state()
        if state.get("running"):
            probe = state.get("last_bandwidth_probe") or {}
            cap = int(probe.get("cap_bytes_per_sec", 0))
            try:
                new_gid = core.aria2_add_download(item, cap_bytes_per_sec=cap, port=port)
            except Exception:
                new_gid = None
            if new_gid:
                with storage_locked():
                    live_items = core.load_queue()
                    for it in live_items:
                        if it.get("id") == item_id:
                            it["gid"] = new_gid
                            it["status"] = "active"
                            break
                    core.save_queue(live_items)
                _aria2_apply_priority(new_gid, int(item.get("priority", 0)))
                item["gid"] = new_gid
                item["status"] = "active"
    return {"ok": True, "item": dict(item)}


def remove_queue_item(item_id: str, port: int = 6800) -> dict[str, Any]:
    core = _core()
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        before = dict(item)
        gid = item.get("gid") or None
        should_remove_aria2 = gid and item.get("status") in {
            "active",
            "queued",
            "paused",
        }
    if should_remove_aria2:
        try:
            core.aria2_remove(gid, port=port, timeout=5)
        except Exception:
            try:
                core.aria2_remove_download_result(gid, port=port, timeout=5)
            except Exception:
                pass
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        removed_item = dict(item)
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        removed_item["cancelled_at"] = now
        removed_item["removed_at"] = now
        removed_item["status"] = "cancelled"
        items.pop(idx)
        core.save_queue(items)
        core.archive_item(removed_item)
        core.record_action(
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
    core = _core()
    with storage_locked():
        items, item, idx = _find_queue_item_by_id(item_id)
        if item is None:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"item {item_id} not found",
            }
        if item.get("status") not in {"error", "failed", "stopped"}:
            return {
                "ok": False,
                "error": "invalid_state",
                "message": f"cannot retry item in status '{item.get('status')}'",
            }
        before = dict(item)
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        item["status"] = "queued"
        for key in (
            "gid",
            "error_code",
            "error_message",
            "error_at",
            "live_status",
            "rpc_failures",
            "recovered",
            "recovered_at",
            "recovery_session_id",
        ):
            item.pop(key, None)
        state = core.load_state()
        sid = state.get("session_id")
        if sid:
            item["session_id"] = sid
            history = item.get("session_history") or []
            history.append({"session_id": sid, "joined_at": now, "reason": "retry"})
            item["session_history"] = history
        core.save_queue(items)
        core.record_action(
            action="retry",
            target="queue_item",
            outcome="changed",
            reason="user_retry_item",
            before={"item": before},
            after={"item": dict(item)},
            detail={"item_id": item_id},
        )
    if state.get("running"):
        probe = state.get("last_bandwidth_probe") or {}
        cap = int(probe.get("cap_bytes_per_sec", 0))
        try:
            gid = core.aria2_add_download(item, cap_bytes_per_sec=cap)
        except Exception:
            gid = None
        if gid:
            with storage_locked():
                live_items = core.load_queue()
                for it in live_items:
                    if it.get("id") == item_id:
                        it["gid"] = gid
                        it["status"] = "active"
                        break
                core.save_queue(live_items)
            _aria2_apply_priority(gid, int(item.get("priority", 0)))
            item["gid"] = gid
            item["status"] = "active"
    return {"ok": True, "item": dict(item)}




def post_action(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "reason": item.get("post_action_rule", "pending"),
        "detail": "post action policy not defined yet",
        "item_id": item["id"],
    }
