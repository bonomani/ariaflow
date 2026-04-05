from __future__ import annotations

from urllib.parse import urlparse

from ..api import (
    aria2_change_options,
)
from .helpers import _error_payload


def get_aria2_global_option(h: object, parsed: object) -> None:
    from ..aria2_rpc import aria2_current_global_options
    h._send_json(aria2_current_global_options())


def get_aria2_option(h: object, parsed: object) -> None:
    query = dict(
        part.split("=", 1) if "=" in part else (part, "")
        for part in urlparse(h.path).query.split("&")
        if part
    )
    gid = query.get("gid", "").strip()
    if not gid:
        h._send_json(
            _error_payload("missing_gid", "gid query parameter required"),
            status=400,
        )
        return
    try:
        from ..core import aria2_get_option
        result = aria2_get_option(gid)
        h._send_json(result)
    except Exception as exc:
        h._send_json(
            _error_payload("rpc_error", "internal error"),
            status=500,
        )


def get_aria2_option_tiers(h: object, parsed: object) -> None:
    from ..aria2_rpc import _MANAGED_ARIA2_OPTIONS, _SAFE_ARIA2_OPTIONS
    from ..core import _pref_value

    h._send_json({
        "managed": sorted(_MANAGED_ARIA2_OPTIONS),
        "safe": sorted(_SAFE_ARIA2_OPTIONS),
        "unsafe_enabled": bool(_pref_value("aria2_unsafe_options", False)),
    })


def post_aria2_change_global_option(h: object, payload: object, path: str) -> None:
    if not isinstance(payload, dict) or not payload:
        h._send_json(
            _error_payload(
                "invalid_payload",
                "expected a JSON object with option key-value pairs",
            ),
            status=400,
        )
        return
    options = {str(k): str(v) for k, v in payload.items()}
    result = aria2_change_options(options)
    if not result.get("ok", True):
        h._send_json(result, status=400)
        return
    h._send_json(result)


def post_aria2_change_option(h: object, payload: object, path: str) -> None:
    if not isinstance(payload, dict):
        h._send_json(
            _error_payload("invalid_payload", "expected {gid, options}"),
            status=400,
        )
        return
    gid = str(payload.get("gid", "")).strip()
    options = payload.get("options")
    if not gid or not isinstance(options, dict):
        h._send_json(
            _error_payload("invalid_payload", "expected {gid: string, options: {...}}"),
            status=400,
        )
        return
    try:
        from ..core import aria2_change_option
        aria2_change_option(gid, {str(k): str(v) for k, v in options.items()})
        h._send_json({"ok": True, "gid": gid, "applied": options})
    except Exception:
        h._send_json(
            _error_payload("rpc_error", "internal error"),
            status=500,
        )


def post_aria2_set_limits(h: object, payload: object, path: str) -> None:
    """Set managed bandwidth/seed options via dedicated functions."""
    if not isinstance(payload, dict):
        h._send_json(
            _error_payload("invalid_payload", "expected JSON object"),
            status=400,
        )
        return
    from ..core import (
        aria2_set_max_overall_download_limit,
        aria2_set_max_overall_upload_limit,
        aria2_set_max_download_limit,
        aria2_set_max_upload_limit,
        aria2_set_seed_ratio,
        aria2_set_seed_time,
    )
    applied = {}
    errors = []
    setters = {
        "max_overall_download_limit": lambda v: aria2_set_max_overall_download_limit(int(v)),
        "max_overall_upload_limit": lambda v: aria2_set_max_overall_upload_limit(int(v)),
        "max_download_limit": lambda v: aria2_set_max_download_limit(str(payload["gid"]), int(v)) if "gid" in payload else None,
        "max_upload_limit": lambda v: aria2_set_max_upload_limit(str(payload["gid"]), int(v)) if "gid" in payload else None,
        "seed_ratio": lambda v: aria2_set_seed_ratio(float(v)),
        "seed_time": lambda v: aria2_set_seed_time(int(v)),
    }
    for key, setter in setters.items():
        if key in payload:
            try:
                setter(payload[key])
                applied[key] = payload[key]
            except Exception:
                errors.append(key)
    h._send_json({"ok": len(errors) == 0, "applied": applied, "errors": errors})
