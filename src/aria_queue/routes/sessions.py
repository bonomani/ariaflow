from __future__ import annotations

from ..api import (
    load_queue,
    load_session_history,
    load_state,
    record_action,
    session_stats,
    start_new_state_session,
    summarize_queue,
)
from .helpers import _error_payload


def get_sessions(h: object, parsed: object) -> None:
    query = dict(
        part.split("=", 1) if "=" in part else (part, "")
        for part in parsed.query.split("&")
        if part
    )
    try:
        limit = max(1, min(200, int(query.get("limit", "50"))))
    except ValueError:
        limit = 50
    h._send_json({"sessions": load_session_history(limit=limit)})


def get_session_stats(h: object, parsed: object) -> None:
    query = dict(
        part.split("=", 1) if "=" in part else (part, "")
        for part in parsed.query.split("&")
        if part
    )
    sid = query.get("session_id") or None
    h._send_json(session_stats(session_id=sid))


def post_session(h: object, payload: object, path: str) -> None:
    action = str(payload.get("action", "")).strip()
    if action != "new":
        h._send_json(
            _error_payload("unsupported_action", f"unknown action: {action}"), status=400
        )
        return
    before = {"state": load_state(), "queue": summarize_queue(load_queue())}
    state = start_new_state_session(reason="manual_new_session")
    h._invalidate_status_cache()
    after = {"state": load_state(), "queue": summarize_queue(load_queue())}
    result = {"ok": True, "session": state}
    record_action(
        action="session",
        target="system",
        outcome="changed",
        reason="new_session",
        before=before,
        after=after,
        detail={
            "session_id": state.get("session_id"),
            "session_started_at": state.get("session_started_at"),
        },
    )
    h._send_json(result)
