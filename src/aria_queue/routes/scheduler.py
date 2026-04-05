from __future__ import annotations

from ..api import (
    load_queue,
    load_state,
    pause_active_transfer,
    record_action,
    resume_active_transfer,
    run_ucc,
    stop_background_process,
    summarize_queue,
)
from .helpers import _error_payload


# ── Single-use helper ──

def _resolve_auto_preflight_override(
    payload: object,
) -> tuple[bool | None, dict[str, object] | None]:
    if not isinstance(payload, dict):
        return None, _error_payload("invalid_payload", "expected a JSON object")
    raw_value = payload.get("auto_preflight_on_run")
    if raw_value is None:
        return None, None
    if isinstance(raw_value, bool):
        return raw_value, None
    return None, _error_payload(
        "invalid_auto_preflight_on_run",
        "auto_preflight_on_run must be a boolean when provided",
    )


# ── Route handlers ──

def get_scheduler(h: object, parsed: object) -> None:
    state = load_state()
    running = bool(state.get("running"))
    paused = bool(state.get("paused"))
    stop_requested = bool(state.get("stop_requested"))
    if stop_requested:
        scheduler_status = "stopping"
    elif running and paused:
        scheduler_status = "paused"
    elif running:
        scheduler_status = "running"
    else:
        scheduler_status = "idle"
    h._send_json(
        {
            "status": scheduler_status,
            "running": running,
            "paused": paused,
            "stop_requested": stop_requested,
            "session_id": state.get("session_id"),
            "session_started_at": state.get("session_started_at"),
            "session_closed_at": state.get("session_closed_at"),
            "_rev": state.get("_rev", 0),
        }
    )


def post_scheduler_start(h: object, payload: object, path: str) -> None:
    if not isinstance(payload, dict):
        payload = {}
    before = {"state": load_state(), "queue": summarize_queue(load_queue())}
    from .. import webapp as _wa
    override, override_error = _resolve_auto_preflight_override(payload)
    if override_error is not None:
        h._send_json(override_error, status=400)
        return
    effective_auto_preflight = (
        _wa.auto_preflight_on_run() if override is None else override
    )
    if effective_auto_preflight:
        preflight_result = _wa.preflight()
        record_action(
            action="preflight",
            target="system",
            outcome="converged" if preflight_result.get("status") == "pass" else "blocked",
            reason=preflight_result.get("status", "unknown"),
            before=before,
            after={"state": load_state(), "queue": summarize_queue(load_queue()), "preflight": preflight_result},
            detail=preflight_result,
        )
        if preflight_result.get("exit_code") != 0:
            blocked = {
                "ok": False,
                "action": "start",
                "error": "preflight_blocked",
                "message": "preflight failed before start",
                "effective_auto_preflight_on_run": True,
                "preflight": preflight_result,
            }
            record_action(
                action="run",
                target="queue",
                outcome="blocked",
                reason="preflight_blocked",
                before=before,
                after={"state": load_state(), "queue": summarize_queue(load_queue()), "scheduler": blocked},
                detail=blocked,
            )
            h._invalidate_status_cache()
            h._send_json(blocked, status=409)
            return
    result = _wa.start_background_process()
    response: dict[str, object] = {
        "ok": True,
        "action": "start",
        "effective_auto_preflight_on_run": effective_auto_preflight,
        "result": result,
    }
    record_action(
        action="run",
        target="queue",
        outcome="changed" if result.get("started") else "unchanged",
        reason=result.get("reason", "unknown"),
        before=before,
        after={"state": load_state(), "queue": summarize_queue(load_queue()), "scheduler": response},
        detail=response,
    )
    h._invalidate_status_cache()
    h._send_json(response)


def post_scheduler_stop(h: object, payload: object, path: str) -> None:
    before = {"state": load_state(), "queue": summarize_queue(load_queue())}
    result = stop_background_process()
    response: dict[str, object] = {"ok": True, "action": "stop", "result": result}
    record_action(
        action="run",
        target="queue",
        outcome="changed" if result.get("stopped") else "unchanged",
        reason=result.get("reason", "unknown"),
        before=before,
        after={"state": load_state(), "queue": summarize_queue(load_queue()), "scheduler": response},
        detail=response,
    )
    h._invalidate_status_cache()
    h._send_json(response)


def post_pause(h: object, payload: object, path: str) -> None:
    result = pause_active_transfer()
    h._invalidate_status_cache()
    h._send_json(result)


def post_resume(h: object, payload: object, path: str) -> None:
    result = resume_active_transfer()
    h._invalidate_status_cache()
    h._send_json(result)


def post_preflight(h: object, payload: object, path: str) -> None:
    from .. import webapp as _wa
    before = {"state": load_state(), "queue": summarize_queue(load_queue())}
    result = _wa.preflight()
    result["aria2"] = _wa.aria2_status()
    result["bandwidth"] = _wa.aria2_current_bandwidth()
    record_action(
        action="preflight",
        target="system",
        outcome="converged" if result.get("status") == "pass" else "blocked",
        reason=result.get("status", "unknown"),
        before=before,
        after={
            "state": load_state(),
            "queue": summarize_queue(load_queue()),
            "preflight": result,
        },
        detail=result,
    )
    h._invalidate_status_cache()
    h._send_json(result)


def post_ucc(h: object, payload: object, path: str) -> None:
    before = {"state": load_state(), "queue": summarize_queue(load_queue())}
    result = run_ucc()
    record_action(
        action="ucc",
        target="queue",
        outcome=result.get("result", {}).get("outcome", "unknown"),
        observation=result.get("result", {}).get("observation", "unknown"),
        reason=result.get("result", {}).get("reason", "unknown"),
        before=before,
        after={
            "state": load_state(),
            "queue": summarize_queue(load_queue()),
            "ucc": result,
        },
        detail=result,
    )
    h._invalidate_status_cache()
    h._send_json(result)
