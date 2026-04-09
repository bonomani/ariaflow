from __future__ import annotations

from ..api import (
    load_declaration,
    save_declaration,
)
from .helpers import _error_payload


def get_declaration(h: object, parsed: object) -> None:
    h._send_json(load_declaration())


def post_declaration(h: object, payload: object, path: str) -> None:
    declaration = payload if isinstance(payload, dict) else {}
    saved = save_declaration(declaration)
    h._invalidate_status_cache()
    h._send_json({"saved": True, "declaration": saved})


def patch_declaration_preferences(h: object, payload: object) -> None:
    if not isinstance(payload, dict) or not payload:
        h._send_json(
            _error_payload("invalid_payload", "expected {preference_name: value}"),
            status=400,
        )
        return
    from ..core import load_declaration, save_declaration, record_action, storage_locked

    with storage_locked():
        declaration = load_declaration()
        preferences = declaration.get("uic", {}).get("preferences", [])
        applied = {}
        unknown = []
        for key, value in payload.items():
            found = False
            for pref in preferences:
                if pref.get("name") == key:
                    before_value = pref.get("value")
                    pref["value"] = value
                    applied[key] = {"before": before_value, "after": value}
                    found = True
                    break
            if not found:
                unknown.append(key)
        if unknown:
            h._send_json(
                _error_payload("unknown_preferences", f"unknown: {unknown}"),
                status=400,
            )
            return
        saved = save_declaration(declaration)
        record_action(
            action="patch_preferences",
            target="declaration",
            outcome="changed",
            reason="user_patch_preferences",
            before={},
            after={"applied": applied},
            detail={"applied": applied},
        )
    h._invalidate_status_cache()
    h._send_json({"ok": True, "applied": applied, "declaration": saved})
