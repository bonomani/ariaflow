from __future__ import annotations

import datetime
import shutil
import time
import threading
from pathlib import Path
from typing import Any


def _core() -> Any:
    """Lazy import to allow patching through aria_queue.core."""
    from . import core
    return core


def check_disk_space() -> tuple[bool, float]:
    """Check if disk usage is below the configured threshold.

    Returns (ok, percent_used). ok is False if over limit.
    """
    core = _core()
    raw = core._pref_value("max_disk_usage_percent", 90)
    max_percent = int(raw) if raw is not None else 90
    if max_percent == 0:
        return True, 0.0
    download_dir = str(core._pref_value("download_dir", "") or "")
    path = Path(download_dir) if download_dir else Path.cwd()
    try:
        usage = shutil.disk_usage(path)
        percent_used = round((usage.used / usage.total) * 100, 1)
    except OSError:
        return True, 0.0  # can't check — allow download
    return percent_used < max_percent, percent_used


def start_background_process(port: int = 6800) -> dict[str, Any]:
    core = _core()
    with core.storage_locked():
        state = core.ensure_state_session()
        if state.get("running"):
            return {"started": False, "reason": "already_running"}

        state["running"] = True
        state["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        core.save_state(state)

    def _scheduler() -> None:
        try:
            core.process_queue(port=port)
        except Exception as exc:
            current = core.load_state()
            current["last_error"] = str(exc)
            current["running"] = False
            current["active_gid"] = None
            current["active_url"] = None
            core.save_state(current)

    thread = threading.Thread(target=_scheduler, daemon=True)
    thread.start()
    return {"started": True, "reason": "background"}



def process_queue(port: int = 6800) -> list[dict[str, Any]]:
    core = _core()
    core.ensure_storage()
    core.ensure_state_session()
    try:
        core.cleanup_queue_state()
    except Exception as exc:
        core.record_action(
            action="error", target="queue", outcome="failed",
            reason="cleanup_failed", detail={"error": str(exc)},
        )
    core.aria2_ensure_daemon(port=port)
    try:
        core.deduplicate_active_transfers(port=port)
    except Exception as exc:
        core.record_action(
            action="error", target="queue", outcome="failed",
            reason="deduplicate_failed", detail={"error": str(exc)},
        )
    try:
        core.reconcile_live_queue(port=port, timeout=5, adopt_missing=True)
    except Exception as exc:
        core.record_action(
            action="error", target="queue", outcome="failed",
            reason="reconcile_failed", detail={"error": str(exc)},
        )
    with core.storage_locked():
        state = core.load_state()
        probe, cap_mbps, cap_bytes_per_sec = core._apply_bandwidth_probe(
            port=port, state=state, force=True
        )
        items = core.load_queue()
        state["running"] = True
        state["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        core.save_state(state)
    for item in items:
        gid = str(item.get("gid") or "")
        if not gid:
            continue
        try:
            core.aria2_set_max_download_limit(gid, cap_bytes_per_sec, port=port)
        except Exception as exc:
            core.record_action(
                action="error", target="queue_item", outcome="failed",
                reason="set_download_limit_failed", detail={"gid": gid, "error": str(exc)},
            )

    limit = core.max_simultaneous_downloads()
    if limit > 0:
        try:
            core.aria2_change_global_option({"max-concurrent-downloads": str(limit)}, port=port)
        except Exception as exc:
            core.record_action(
                action="error", target="queue", outcome="failed",
                reason="set_concurrency_failed", detail={"error": str(exc)},
            )

    def _finalize_primary_state(
        items_snapshot: list[dict[str, Any]], active_infos: list[dict[str, Any]], poll_ok: bool = True
    ) -> None:
        current = core.load_state()
        current["running"] = bool(current.get("running"))
        current["paused"] = bool(current.get("paused"))
        current["session_last_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if active_infos:
            best = sorted(
                active_infos,
                key=lambda info: (
                    float(info.get("completedLength") or 0)
                    / max(float(info.get("totalLength") or 1), 1.0),
                    float(info.get("completedLength") or 0),
                    float(info.get("downloadSpeed") or 0),
                ),
                reverse=True,
            )[0]
            current["active_gid"] = best.get("gid")
            match = core._queue_item_for_active_info(best, items_snapshot)
            current["active_url"] = (
                match.get("url") if match else core._active_item_url(best)
            )
        elif poll_ok:
            current["active_gid"] = None
            current["active_url"] = None
        core.save_state(current)

    def _apply_transfer_fields(item: dict[str, Any], info: dict[str, Any]) -> None:
        _ARIA2_TO_ITEM = {
            "downloadSpeed": "download_speed",
            "completedLength": "completed_length",
            "totalLength": "total_length",
            "files": "files",
        }
        for aria2_key, item_key in _ARIA2_TO_ITEM.items():
            if aria2_key in info:
                item[item_key] = info.get(aria2_key)

    def _queued_info(
        item: dict[str, Any], gid: str, status_name: str
    ) -> dict[str, Any]:
        return {
            "gid": gid,
            "status": status_name,
            "completedLength": str(item.get("completed_length") or "0"),
            "totalLength": str(item.get("total_length") or "0"),
            "downloadSpeed": str(item.get("download_speed") or "0"),
            "files": [{"uris": [{"uri": item.get("url")}]}] if item.get("url") else [],
        }

    _MAX_RPC_FAILURES = 5

    def _poll_tracked_jobs(
        items_snapshot: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        running_infos: list[dict[str, Any]] = []
        had_rpc_success = False

        # Collect items that need polling
        pollable: list[tuple[dict[str, Any], str]] = []
        for item in items_snapshot:
            if item.get("status") in {"complete", "error"}:
                continue
            gid = str(item.get("gid") or "")
            if not gid:
                continue
            pollable.append((item, gid))

        if not pollable:
            return running_infos, True

        # Batch RPC: one multicall instead of N sequential calls
        results_map: dict[str, dict[str, Any] | Exception] = {}
        gids = [gid for _, gid in pollable]
        try:
            calls = [
                {"methodName": "aria2.tellStatus", "params": [gid]}
                for gid in gids
            ]
            batch_results = core.aria2_multicall(calls, port=port, timeout=10)
            for gid, result in zip(gids, batch_results):
                if isinstance(result, list) and result:
                    results_map[gid] = result[0]
                else:
                    results_map[gid] = RuntimeError(f"unexpected multicall result: {result}")
        except Exception as exc:
            # Fallback: sequential calls if multicall fails
            core.record_action(
                action="error", target="queue", outcome="failed",
                reason="multicall_failed", detail={"error": str(exc), "fallback": "sequential"},
            )
            for _, gid in pollable:
                try:
                    results_map[gid] = core.aria2_tell_status(gid, port=port, timeout=5)
                except Exception as exc:
                    results_map[gid] = exc

        # Process results
        for item, gid in pollable:
            before_item = dict(item)
            result = results_map.get(gid)
            if isinstance(result, Exception):
                info = None
            else:
                info = result

            if info is None:
                rpc_failures = item.get("rpc_failures", 0) + 1
                item["rpc_failures"] = rpc_failures
                if rpc_failures >= _MAX_RPC_FAILURES:
                    item["status"] = "error"
                    item["error_code"] = "rpc_unreachable"
                    item["error_message"] = (
                        f"aria2 RPC unreachable after {rpc_failures} consecutive attempts"
                    )
                    item["error_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    item.pop("live_status", None)
                    item.pop("gid", None)
                    core.record_action(
                        action="error",
                        target="queue_item",
                        outcome="failed",
                        reason="rpc_unreachable",
                        before={"item": before_item},
                        after={"item": dict(item)},
                        detail={
                            "item_id": item.get("id"),
                            "gid": gid,
                            "url": item.get("url"),
                            "rpc_failures": rpc_failures,
                        },
                    )
                continue
            had_rpc_success = True
            remote_status = str(info.get("status") or "")
            item["gid"] = gid
            item.pop("rpc_failures", None)
            if remote_status:
                item["live_status"] = remote_status
            _apply_transfer_fields(item, info)
            if remote_status == "active":
                item["status"] = "active"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                running_infos.append(info)
                core.log_transfer_poll(gid=gid, item=item, info=info, cap_mbps=cap_mbps)
                if info.get("errorCode") and info["errorCode"] != "0":
                    cap_local = max(
                        int(core._BYTES_PER_MEGABIT), int(cap_bytes_per_sec * 0.75)
                    )
                    core.aria2_set_max_overall_download_limit(cap_local, port=port)
                continue
            if remote_status == "waiting":
                item["status"] = "waiting"
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
                item["status"] = "complete"
                item["error_code"] = None
                item["error_message"] = None
                item["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                item["post_action"] = core.post_action(item)
                core.record_action(
                    action="complete",
                    target="queue_item",
                    outcome="converged",
                    reason="download_complete",
                    before={"item": before_item},
                    after={"item": dict(item), "post_action": item.get("post_action")},
                    detail={
                        "item_id": item.get("id"),
                        "gid": gid,
                        "url": item.get("url"),
                        "result": item.get("post_action"),
                    },
                )
                continue
            if remote_status == "error":
                item["status"] = "error"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                item["error_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                core.record_action(
                    action="error",
                    target="queue_item",
                    outcome="failed",
                    reason="download_error",
                    before={"item": before_item},
                    after={
                        "item": dict(item),
                        "error_code": item.get("error_code"),
                        "error_message": item.get("error_message"),
                    },
                    detail={
                        "item_id": item.get("id"),
                        "gid": gid,
                        "url": item.get("url"),
                        "error_code": item.get("error_code"),
                        "error_message": item.get("error_message"),
                    },
                )
                continue
            if remote_status == "removed":
                item["status"] = "stopped"
                item["error_code"] = "removed"
                item["error_message"] = "download removed from aria2"
                item.pop("gid", None)
                item.pop("live_status", None)
        return running_infos, had_rpc_success

    while True:
        # Phase 1: load state (locked)
        with core.storage_locked():
            items = core.load_queue()
            state = core.load_state()
            is_paused = state.get("paused")

        # Phase 2: RPC calls (unlocked — no storage lock held)
        running_infos, poll_ok = _poll_tracked_jobs(items)
        probe, cap_mbps, cap_bytes_per_sec = core._apply_bandwidth_probe(
            port=port, state=state
        )

        # Auto-retry: re-queue error items that haven't exhausted retries
        max_retries = int(core._pref_value("max_retries", 3) or 3)
        backoff = int(core._pref_value("retry_backoff_seconds", 30) or 30)
        now_ts = time.time()
        if max_retries > 0 and not is_paused:
            for item in items:
                if item.get("status") != "error":
                    continue
                if item.get("error_code") == "rpc_unreachable":
                    continue  # don't auto-retry if aria2 is down
                retry_count = int(item.get("retry_count") or 0)
                if retry_count >= max_retries:
                    continue
                next_retry = float(item.get("next_retry_at") or 0)
                if next_retry > 0 and now_ts < next_retry:
                    continue  # backoff not elapsed
                # Auto-retry this item
                before_item = dict(item)
                item["retry_count"] = retry_count + 1
                item["status"] = "queued"
                for key in ("gid", "error_code", "error_message", "error_at", "live_status", "rpc_failures"):
                    item.pop(key, None)
                item["next_retry_at"] = now_ts + backoff * (retry_count + 1)
                core.record_action(
                    action="auto_retry",
                    target="queue_item",
                    outcome="changed",
                    reason="auto_retry",
                    before={"item": before_item},
                    after={"item": dict(item)},
                    detail={
                        "item_id": item.get("id"),
                        "retry_count": item["retry_count"],
                        "max_retries": max_retries,
                        "next_retry_at": item["next_retry_at"],
                    },
                )

        # Expire old seeds
        max_seed_hours = int(core._pref_value("distribute_max_seed_hours", 72) or 72)
        max_active_seeds = int(core._pref_value("distribute_max_active_seeds", 10) or 10)
        seeding_items = sorted(
            [i for i in items if i.get("distribute_status") == "seeding"],
            key=lambda i: i.get("distribute_started_at", ""),
        )
        for item in seeding_items:
            should_expire = False
            # Time-based expiration
            if max_seed_hours > 0:
                started = item.get("distribute_started_at", "")
                if started:
                    try:
                        start_dt = datetime.datetime.strptime(started[:19], "%Y-%m-%dT%H:%M:%S")
                        start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
                        age_hours = (datetime.datetime.now(datetime.timezone.utc) - start_dt).total_seconds() / 3600
                        if age_hours > max_seed_hours:
                            should_expire = True
                    except (ValueError, TypeError):
                        pass
            # Count-based expiration (oldest first)
            if max_active_seeds > 0 and not should_expire:
                idx = seeding_items.index(item)
                if len(seeding_items) - idx > max_active_seeds:
                    should_expire = True
            if should_expire:
                seed_gid = item.get("distribute_seed_gid")
                if seed_gid:
                    try:
                        core.aria2_remove(seed_gid, port=port)
                    except Exception as exc:
                        core.record_action(
                            action="error", target="queue_item", outcome="failed",
                            reason="seed_remove_failed",
                            detail={"gid": seed_gid, "error": str(exc)},
                        )
                torrent_path = item.get("distribute_torrent_path")
                if torrent_path:
                    try:
                        import os
                        os.remove(torrent_path)
                    except Exception as exc:
                        core.record_action(
                            action="error", target="queue_item", outcome="failed",
                            reason="torrent_file_remove_failed",
                            detail={"path": torrent_path, "error": str(exc)},
                        )
                item["distribute_status"] = "expired"
                item.pop("distribute_seed_gid", None)
                core.record_action(
                    action="seed_expired",
                    target="queue_item",
                    outcome="changed",
                    reason="seed_expiration",
                    before={},
                    after={"item_id": item.get("id"), "infohash": item.get("distribute_infohash")},
                    detail={"item_id": item.get("id"), "infohash": item.get("distribute_infohash")},
                )

        current_running_infos = list(running_infos)
        if not is_paused:
            disk_ok, disk_percent = check_disk_space()
            if not disk_ok:
                core.record_action(
                    action="error", target="queue", outcome="blocked",
                    reason="disk_full",
                    detail={"disk_usage_percent": disk_percent},
                )
            for item in sorted(
                items, key=lambda i: int(i.get("priority", 0)), reverse=True
            ):
                if not disk_ok:
                    break
                if item.get("status") != "queued":
                    continue
                if item.get("gid"):
                    continue
                before_item = dict(item)
                try:
                    gid = core.aria2_add_download(item, cap_bytes_per_sec=cap_bytes_per_sec, port=port)
                except Exception as exc:
                    core.record_action(
                        action="error", target="queue_item", outcome="failed",
                        reason="add_download_failed",
                        detail={"item_id": item.get("id"), "error": str(exc)},
                    )
                    continue
                item["status"] = "active"
                item.pop("live_status", None)
                item["gid"] = gid
                core.record_action(
                    action="run",
                    target="queue_item",
                    outcome="changed",
                    reason="download_started",
                    before={"item": before_item},
                    after={"item": dict(item), "gid": gid, "cap_mbps": cap_mbps},
                    detail={
                        "item_id": item.get("id"),
                        "gid": gid,
                        "url": item.get("url"),
                        "cap_mbps": cap_mbps,
                    },
                )
                current_running_infos.append(_queued_info(item, gid, "waiting"))
                core._aria2_apply_priority(gid, int(item.get("priority", 0)))

        # Phase 3: save state (locked)
        # Phase 3: save state (locked)
        with core.storage_locked():
            core.save_queue(items)
            _finalize_primary_state(items, current_running_infos, poll_ok=poll_ok)

        time.sleep(2)


def auto_preflight_on_run() -> bool:
    from .contracts import load_declaration

    declaration = load_declaration()
    for pref in declaration.get("uic", {}).get("preferences", []):
        if pref.get("name") == "auto_preflight_on_run":
            return bool(pref.get("value", False))
    return False


def get_active_progress(port: int = 6800) -> dict[str, Any] | None:
    core = _core()
    state = core.load_state()
    gid = state.get("active_gid")
    if not gid:
        return None
    try:
        info = core.aria2_tell_status(gid, port=port)
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
