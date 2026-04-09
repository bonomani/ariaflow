from __future__ import annotations

from ..api import (
    load_session_history,
    session_stats,
)


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
