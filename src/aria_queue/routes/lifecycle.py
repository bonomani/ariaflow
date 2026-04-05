from __future__ import annotations

from ..api import (
    homebrew_install_ariaflow,
    homebrew_uninstall_ariaflow,
    install_aria2_launchd,
    load_state,
    record_action,
    status_all,
    ucc_record,
    uninstall_aria2_launchd,
)
from .helpers import _error_payload


# ── Single-use helper ──

def _lifecycle_payload() -> dict[str, object]:
    lifecycle = status_all()
    state = load_state()
    lifecycle.update({
        "session_id": state.get("session_id"),
        "session_started_at": state.get("session_started_at"),
        "session_last_seen_at": state.get("session_last_seen_at"),
        "session_closed_at": state.get("session_closed_at"),
        "session_closed_reason": state.get("session_closed_reason"),
    })
    return lifecycle


# ── Route handlers ──

def get_lifecycle(h: object, parsed: object) -> None:
    h._send_json(_lifecycle_payload())


def post_lifecycle_action(h: object, payload: object, path: str) -> None:
    from .. import webapp as _wa
    if not _wa.is_macos():
        h._send_json(_error_payload("macos_only", "this endpoint requires macOS"), status=400)
        return
    target = str(payload.get("target", "")).strip()
    action = str(payload.get("action", "")).strip()
    before = {"lifecycle": status_all()}
    try:
        if target == "ariaflow" and action == "install":
            commands = homebrew_install_ariaflow(dry_run=False)
            result = {
                "ariaflow": ucc_record(
                    target="ariaflow",
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="install",
                    detail="ariaflow package installed or updated",
                    commands=commands,
                )
            }
        elif target == "ariaflow" and action == "uninstall":
            commands = homebrew_uninstall_ariaflow(dry_run=False)
            result = {
                "ariaflow": ucc_record(
                    target="ariaflow",
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="uninstall",
                    detail="ariaflow package removed",
                    commands=commands,
                )
            }
        elif target == "aria2-launchd" and action == "install":
            commands = install_aria2_launchd(dry_run=False)
            result = {
                "aria2-launchd": ucc_record(
                    target="aria2-launchd",
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="install",
                    detail="optional aria2 launchd service installed or queued for installation",
                    commands=commands,
                )
            }
        elif target == "aria2-launchd" and action == "uninstall":
            commands = uninstall_aria2_launchd(dry_run=False)
            result = {
                "aria2-launchd": ucc_record(
                    target="aria2-launchd",
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="uninstall",
                    detail="optional aria2 launchd removed or queued for removal",
                    commands=commands,
                )
            }
        else:
            h._send_json(
                {
                    "error": "unsupported_action",
                    "target": target,
                    "action": action,
                },
                status=400,
            )
            return
    except Exception as exc:
        record_action(
            action="lifecycle_action",
            target=target or "system",
            outcome="failed",
            reason="exception",
            before=before,
            after={
                "lifecycle": status_all(),
                "target": target,
                "action": action,
            },
            detail={"error": str(exc), "target": target, "action": action},
        )
        h._invalidate_status_cache()
        h._send_json(
            _error_payload("lifecycle_action_failed", "internal error"),
            status=500,
        )
        return
    record_action(
        action="lifecycle_action",
        target=target or "system",
        outcome="changed",
        reason=action or "lifecycle_action",
        before=before,
        after={
            "lifecycle": status_all(),
            "target": target,
            "action": action,
            "result": result,
        },
        detail={"target": target, "action": action, "result": result},
    )
    h._invalidate_status_cache()
    h._send_json(
        {
            "ok": True,
            "target": target,
            "action": action,
            "lifecycle": _lifecycle_payload(),
            "result": result,
        }
    )
