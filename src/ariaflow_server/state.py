from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from .storage import (
    ensure_storage,
    storage_locked,
    read_json,
    write_json,
    state_path,
    action_log_path,
    archive_path,
    sessions_log_path,
)


def _core() -> Any:
    """Lazy import to allow patching through ariaflow_server.core."""
    from . import core

    return core


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
    core = _core()
    with storage_locked():
        payload = dict(entry)
        payload.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        try:
            state = core.load_state()
            session_id = state.get("session_id")
        except Exception:
            state = None
            session_id = None
        if session_id:
            payload.setdefault("session_id", session_id)
            if state is not None:
                state["session_last_seen_at"] = payload["timestamp"]
                core.save_state(state)
        with action_log_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True) + "\n")
        _rotate_action_log()
    # BG-7: push to SSE subscribers (outside storage lock to avoid holding
    # it during network I/O)
    try:
        from . import webapp as _wa

        _wa._sse_publish("action_logged", payload)
    except Exception:
        pass


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
                "session_id": None,
                "session_started_at": None,
                "session_last_seen_at": None,
                "session_closed_at": None,
                "session_closed_reason": None,
            },
        )


def save_state(state: dict[str, Any]) -> None:
    with storage_locked():
        state["_rev"] = int(state.get("_rev", 0)) + 1
        write_json(state_path(), state)


def ensure_state_session() -> dict[str, Any]:
    core = _core()
    with storage_locked():
        state = core.load_state()
        if not state.get("session_id") or state.get("session_closed_at"):
            state["session_id"] = str(uuid4())
            state["session_started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["session_last_seen_at"] = state["session_started_at"]
            state["session_closed_at"] = None
            state["session_closed_reason"] = None
            core.save_state(state)
        return state


def touch_state_session() -> dict[str, Any]:
    core = _core()
    with storage_locked():
        state = core.load_state()
        if state.get("session_id"):
            state["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            core.save_state(state)
        return state


def close_state_session(reason: str = "closed") -> dict[str, Any]:
    core = _core()
    with storage_locked():
        # ASM CR-4: a session may not transition to closed while jobs are
        # still in the active/waiting tier (the ASM "downloading" axis
        # value). Refuse the close — callers must pause or cancel active
        # jobs first. start_new_state_session() handles this by pausing
        # active items before invoking close.
        items = core.load_queue()
        active = [
            it for it in items if str(it.get("status") or "") in ("active", "waiting")
        ]
        if active:
            raise RuntimeError(
                f"ASM CR-4: cannot close session with {len(active)} "
                f"active/waiting job(s); pause or cancel them first"
            )
        state = core.load_state()
        if state.get("session_id") and not state.get("session_closed_at"):
            now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["session_closed_at"] = now
            state["session_closed_reason"] = reason
            state["session_last_seen_at"] = now
            core.save_state(state)
            _log_session_history(state)
        return state


def start_new_state_session(reason: str = "manual_new_session") -> dict[str, Any]:
    core = _core()
    with storage_locked():
        # ASM CR-4: pause any active/waiting jobs in queue.json before
        # closing the session, so the close transition is admissible.
        # This is a state-record pause only — aria2 itself is not paused
        # here because the daemon may not be reachable during rollover;
        # the next session resumes them via the normal scheduler loop.
        items = core.load_queue()
        paused_any = False
        for it in items:
            if str(it.get("status") or "") in ("active", "waiting"):
                it["status"] = "paused"
                paused_any = True
        if paused_any:
            core.save_queue(items)
        core.close_state_session(reason=reason)
        state = core.load_state()
        state["session_id"] = str(uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state["session_started_at"] = now
        state["session_last_seen_at"] = now
        state["session_closed_at"] = None
        state["session_closed_reason"] = None
        core.save_state(state)
        return state


def _log_session_history(
    state: dict[str, Any], items: list[dict[str, Any]] | None = None
) -> None:
    """Append a session summary to sessions.jsonl."""
    session_id = state.get("session_id")
    if not session_id:
        return
    if items is None:
        items = _core().load_queue()
    session_items = [i for i in items if i.get("session_id") == session_id]
    entry = {
        "session_id": session_id,
        "started_at": state.get("session_started_at"),
        "closed_at": state.get("session_closed_at"),
        "closed_reason": state.get("session_closed_reason"),
        "items_total": len(session_items),
        "items_done": sum(1 for i in session_items if i.get("status") in ("complete",)),
        "items_error": sum(
            1 for i in session_items if i.get("status") in ("error", "failed")
        ),
        "items_queued": sum(1 for i in session_items if i.get("status") == "queued"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with storage_locked():
        ensure_storage()
        with sessions_log_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


def load_session_history(limit: int = 50) -> list[dict[str, Any]]:
    with storage_locked():
        path = sessions_log_path()
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
                pass
        return entries


def session_stats(session_id: str | None = None) -> dict[str, Any]:
    state = load_state()
    if session_id is None:
        session_id = state.get("session_id")
    items = _core().load_queue()
    archived = _core().load_archive()
    session_items = [i for i in items if i.get("session_id") == session_id]
    session_archived = [i for i in archived if i.get("session_id") == session_id]
    all_items = session_items + session_archived
    return {
        "session_id": session_id,
        "started_at": state.get("session_started_at")
        if session_id == state.get("session_id")
        else None,
        "items_total": len(all_items),
        "items_active": len(session_items),
        "items_archived": len(session_archived),
        "items_done": sum(1 for i in all_items if i.get("status") in ("complete",)),
        "items_error": sum(
            1 for i in all_items if i.get("status") in ("error", "failed")
        ),
        "items_queued": sum(1 for i in all_items if i.get("status") == "queued"),
        "items_downloading": sum(1 for i in all_items if i.get("status") == "active"),
        "items_paused": sum(1 for i in all_items if i.get("status") == "paused"),
        "bytes_completed": sum(int(i.get("completed_length") or 0) for i in all_items),
    }


def load_archive() -> list[dict[str, Any]]:
    with storage_locked():
        data = read_json(archive_path(), {"items": []})
        return list(data.get("items", []))


def save_archive(items: list[dict[str, Any]]) -> None:
    with storage_locked():
        write_json(archive_path(), {"items": items})


def archive_item(item: dict[str, Any]) -> None:
    with storage_locked():
        archived = load_archive()
        entry = dict(item)
        entry["archived_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        archived.append(entry)
        save_archive(archived)


def count_archivable(
    items: list[dict[str, Any]],
    max_done_age_hours: int = 168,
) -> int:
    """Count queue items that would be archived by auto_cleanup_queue()."""
    from datetime import datetime, timezone

    now = time.time()
    cutoff_ts = now - (max_done_age_hours * 3600)
    _TERMINAL = {"complete", "error", "failed", "stopped", "removed"}
    count = 0
    for item in items:
        if str(item.get("status") or "") not in _TERMINAL:
            continue
        created = (
            item.get("completed_at")
            or item.get("error_at")
            or item.get("created_at")
            or ""
        )
        try:
            dt = datetime.fromisoformat(created)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            item_ts = dt.timestamp()
        except (ValueError, TypeError):
            item_ts = now
        if item_ts < cutoff_ts:
            count += 1
    return count


def auto_cleanup_queue(
    max_done_age_days: int = 7,
    max_done_age_hours: int | None = None,
    max_done_count: int = 100,
    archive_noncomplete: bool = True,
) -> dict[str, Any]:
    now = time.time()
    if max_done_age_hours is None:
        max_done_age_hours = int(max_done_age_days * 24)
    cutoff_ts = now - (max_done_age_hours * 3600)
    with storage_locked():
        items = _core().load_queue()
        keep: list[dict[str, Any]] = []
        archived_count = 0
        for item in items:
            status = str(item.get("status") or "")
            is_complete = status == "complete"
            is_other_terminal = status in {"error", "failed", "stopped", "removed"}
            if is_complete or (archive_noncomplete and is_other_terminal):
                created = (
                    item.get("completed_at")
                    or item.get("error_at")
                    or item.get("created_at")
                    or ""
                )
                try:
                    from datetime import datetime, timezone

                    dt = datetime.fromisoformat(created)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    item_ts = dt.timestamp()
                except (ValueError, TypeError):
                    item_ts = now
                if item_ts < cutoff_ts:
                    archive_item(item)
                    archived_count += 1
                    continue
            keep.append(item)
        # Also enforce max_done_count
        done_items = [i for i in keep if i.get("status") in ("complete",)]
        if max_done_count > 0 and len(done_items) > max_done_count:
            excess = len(done_items) - max_done_count
            done_to_archive = done_items[:excess]
            for item in done_to_archive:
                archive_item(item)
                keep.remove(item)
                archived_count += 1
        if archived_count > 0:
            _core().save_queue(keep)
            record_action(
                action="auto_cleanup",
                target="queue",
                outcome="changed",
                reason="stale_items_archived",
                before={"total": len(items)},
                after={"total": len(keep), "archived": archived_count},
                detail={
                    "max_done_age_days": max_done_age_days,
                    "max_done_age_hours": max_done_age_hours,
                    "max_done_count": max_done_count,
                    "archive_noncomplete": archive_noncomplete,
                },
            )
    return {"archived": archived_count, "remaining": len(keep)}
