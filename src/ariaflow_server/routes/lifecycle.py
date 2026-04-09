from __future__ import annotations

from ..api import (
    _aria2_install_service,
    _aria2_uninstall_service,
    homebrew_install_ariaflow_server,
    homebrew_uninstall_ariaflow_server,
    load_state,
    record_action,
    status_all,
    ucc_record,
)
from ..platform.detect import is_macos
from .helpers import _error_payload


# ── Single-use helper ──


def _lifecycle_payload() -> dict[str, object]:
    lifecycle = status_all()
    state = load_state()
    lifecycle.update(
        {
            "session_id": state.get("session_id"),
            "session_started_at": state.get("session_started_at"),
            "session_last_seen_at": state.get("session_last_seen_at"),
            "session_closed_at": state.get("session_closed_at"),
            "session_closed_reason": state.get("session_closed_reason"),
        }
    )
    return lifecycle


# ── Route handlers ──


def get_lifecycle(h: object, parsed: object) -> None:
    h._send_json(_lifecycle_payload())


def post_lifecycle_action(h: object, payload: object, path: str) -> None:
    _ARIA2_SERVICE_TARGETS = {"aria2-launchd", "aria2-task", "aria2-systemd", "aria2-service"}
    target = str(payload.get("target", "")).strip()
    action = str(payload.get("action", "")).strip()
    before = {"lifecycle": status_all()}
    try:
        if target == "ariaflow-server" and action == "install":
            if not is_macos():
                h._send_json(
                    _error_payload("use_pipx", "install ariaflow-server via: pipx install ariaflow-server"),
                    status=400,
                )
                return
            commands = homebrew_install_ariaflow_server(dry_run=False)
            result = {
                "ariaflow-server": ucc_record(
                    target="ariaflow-server",
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="install",
                    detail="ariaflow-server package installed or updated",
                    commands=commands,
                )
            }
        elif target == "ariaflow-server" and action == "uninstall":
            if not is_macos():
                h._send_json(
                    _error_payload("use_pipx", "uninstall ariaflow-server via: pipx uninstall ariaflow-server"),
                    status=400,
                )
                return
            commands = homebrew_uninstall_ariaflow_server(dry_run=False)
            result = {
                "ariaflow-server": ucc_record(
                    target="ariaflow-server",
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="uninstall",
                    detail="ariaflow-server package removed",
                    commands=commands,
                )
            }
        elif target in _ARIA2_SERVICE_TARGETS and action == "install":
            svc_target, commands = _aria2_install_service(dry_run=False)
            result = {
                svc_target: ucc_record(
                    target=svc_target,
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="install",
                    detail=f"{svc_target} service installed or queued for installation",
                    commands=commands,
                )
            }
        elif target in _ARIA2_SERVICE_TARGETS and action == "uninstall":
            svc_target, commands = _aria2_uninstall_service(dry_run=False)
            result = {
                svc_target: ucc_record(
                    target=svc_target,
                    observed=True,
                    outcome="changed",
                    completion="complete",
                    reason="uninstall",
                    detail=f"{svc_target} service removed or queued for removal",
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
