from __future__ import annotations

from ..api import (
    load_queue,
    load_state,
    pause_active_transfer,
    record_action,
    resume_active_transfer,
    run_ucc,
    summarize_queue,
)


# ── Route handlers ──


def get_scheduler(h: object, parsed: object) -> None:
    state = load_state()
    running = bool(state.get("running"))
    paused = bool(state.get("paused"))
    if running and paused:
        scheduler_status = "paused"
    elif running:
        scheduler_status = "running"
    else:
        scheduler_status = "starting"
    h._send_json(
        {
            "status": scheduler_status,
            "running": running,
            "paused": paused,
            "session_id": state.get("session_id"),
            "session_started_at": state.get("session_started_at"),
            "session_closed_at": state.get("session_closed_at"),
            "_rev": state.get("_rev", 0),
        }
    )


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
