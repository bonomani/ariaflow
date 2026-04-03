from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from .storage import (
    ensure_storage,
    storage_locked,
)
from .queue_ops import QueueItem
from .transfers import dedup_active_transfer_action
from .bandwidth import _coerce_float


def _core() -> Any:
    """Lazy import to allow patching through aria_queue.core."""
    from . import core
    return core


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


def _queue_item_for_active_info(
    info: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, Any] | None:
    core = _core()
    gid = str(info.get("gid") or "")
    url = _active_item_url(info)
    session_id = core.load_state().get("session_id")
    candidates = [item for item in items if item.get("status") not in {"complete", "error"}]
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
                if current and (
                    current == url
                    or current.split("?")[0].rstrip("/").split("/")[-1] == url_tail
                ):
                    return item
    session_candidates = candidates
    if session_id:
        session_candidates = [
            item
            for item in candidates
            if not item.get("session_id") or item.get("session_id") == session_id
        ]
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
                if current and (
                    current == url
                    or current.split("?")[0].rstrip("/").split("/")[-1] == url_tail
                ):
                    return item
    return None


def _merge_active_status(status: str | None) -> str:
    if status == "active":
        return "active"
    if status in {"paused", "waiting", "complete", "error"}:
        return str(status)
    return str(status or "active")


def _queue_item_preference(item: dict[str, Any]) -> tuple[int, float, int, int]:
    status_rank = {
        "active": 3,
        "waiting": 2,
        "paused": 2,
        "queued": 1,
        "complete": 0,
        "error": 0,
    }.get(str(item.get("status") or ""), 0)
    completed = _coerce_float(item.get("completed_length")) or 0.0
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
    if primary_status not in {"complete", "error"}:
        for key in ("recovery_session_id", "recovered_at"):
            if not primary.get(key) and candidate.get(key):
                primary[key] = candidate.get(key)
                changed = True
    for key in ("download_speed", "completed_length", "total_length", "files"):
        primary_val = _coerce_float(primary.get(key))
        candidate_val = _coerce_float(candidate.get(key))
        if key == "files":
            if not primary.get(key) and candidate.get(key):
                primary[key] = candidate.get(key)
                changed = True
            continue
        if candidate.get(key) is not None and (
            primary.get(key) is None or (candidate_val or 0.0) > (primary_val or 0.0)
        ):
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
    elif status == "complete" and item.get("live_status") is not None:
        item.pop("live_status", None)
        changed = True
    if status == "complete":
        for key in ("recovered", "recovered_at", "recovery_session_id"):
            if item.get(key) is not None:
                item.pop(key, None)
                changed = True
    return changed


def cleanup_queue_state() -> dict[str, Any]:
    core = _core()
    ensure_storage()
    with storage_locked():
        items = core.load_queue()
        before_summary = core.summarize_queue(items)
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
            core.save_queue(survivors)
            core.record_action(
                action="cleanup",
                target="queue",
                outcome="changed",
                reason="queue_rows_normalized",
                before={"summary": before_summary},
                after={"summary": core.summarize_queue(survivors)},
                detail={
                    "removed": max(len(items) - len(survivors), 0),
                    "normalized": normalized,
                },
            )
        return {
            "changed": changed,
            "items": survivors,
            "removed": max(len(items) - len(survivors), 0),
            "normalized": normalized,
        }


def reconcile_live_queue(
    port: int = 6800, timeout: int = 5, adopt_missing: bool = True
) -> dict[str, Any]:
    core = _core()
    ensure_storage()
    with storage_locked():
        state = core.ensure_state_session()
        items = core.load_queue()
        before_summary = core.summarize_queue(items)
    active_infos = core.aria2_tell_active(port=port, timeout=timeout)
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    changed = False
    recovered = 0

    def _collapse_duplicate_rows(
        primary: dict[str, Any], current_gid: str, current_url: str | None
    ) -> None:
        nonlocal changed
        duplicate_keys = {
            key
            for key in ("download_speed", "completed_length", "total_length", "files")
            if primary.get(key) is not None
        }
        survivors: list[dict[str, Any]] = []
        for candidate in items:
            if candidate is primary:
                survivors.append(candidate)
                continue
            candidate_gid = str(candidate.get("gid") or "")
            candidate_url = str(candidate.get("url") or "")
            same_job = bool(
                current_gid and candidate_gid and candidate_gid == current_gid
            )
            same_url = bool(
                current_url and candidate_url and candidate_url == current_url
            )
            if not same_job and not same_url:
                survivors.append(candidate)
                continue
            for key in (
                "output",
                "post_action_rule",
                "session_id",
                "recovery_session_id",
                "recovered_at",
                "error_code",
                "error_message",
            ):
                if not primary.get(key) and candidate.get(key):
                    primary[key] = candidate.get(key)
            if candidate.get("recovered"):
                primary["recovered"] = True
            for key in ("download_speed", "completed_length", "total_length", "files"):
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
        if state.get("session_id") and item.get("session_id") != state.get(
            "session_id"
        ):
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
            core.save_queue(items)
            core.record_action(
                action="reconcile",
                target="queue",
                outcome="changed",
                reason="live_state_merged",
                before={"summary": before_summary},
                after={
                    "summary": core.summarize_queue(items),
                    "recovered": recovered,
                    "active": [
                        str(info.get("gid") or "")
                        for info in active_infos
                        if info.get("gid")
                    ],
                },
                detail={
                    "recovered": recovered,
                    "active_count": len(active_infos),
                    "adopt_missing": adopt_missing,
                },
            )
    return {
        "changed": changed,
        "recovered": recovered,
        "active_count": len(active_infos),
        "items": items,
    }


def deduplicate_active_transfers(port: int = 6800, timeout: int = 5) -> dict[str, Any]:
    core = _core()
    active = core.aria2_tell_active(port=port, timeout=timeout)
    if len(active) < 2:
        return {"changed": False, "kept": [], "paused": []}
    action = dedup_active_transfer_action()
    if action == "ignore":
        return {
            "changed": False,
            "kept": [str(info.get("gid") or "") for info in active if info.get("gid")],
            "paused": [],
        }

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
                float(info.get("completedLength") or 0)
                / max(float(info.get("totalLength") or 1), 1.0),
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
                    core.aria2_remove(gid, port=port, timeout=timeout)
                else:
                    core.aria2_pause(gid, port=port, timeout=timeout)
                paused.append(gid)
                changed = True
            except Exception:
                continue
    if changed:
        core.record_action(
            action="deduplicate",
            target="active_transfer",
            outcome="changed",
            reason="duplicate_active_transfer",
            before={"active": [info.get("gid") for info in active]},
            after={"kept": kept, "paused": paused, "action": action},
            detail={
                "kept": kept,
                "paused": paused,
                "group_count": len(grouped),
                "action": action,
            },
        )
    return {"changed": changed, "kept": kept, "paused": paused, "action": action}
