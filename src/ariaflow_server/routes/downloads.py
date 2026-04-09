from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from ..api import (
    add_queue_item,
    auto_cleanup_queue,
    get_item_files as api_get_item_files,
    load_archive,
    pause_queue_item,
    remove_queue_item,
    resume_queue_item,
    retry_queue_item,
    select_item_files,
    summarize_queue,
)
from .helpers import _error_payload, _validate_item_id, _ALLOWED_URL_SCHEMES


# ── Single-use helpers ──


def _validate_url(url: str) -> str | None:
    """Return error message if URL is unsafe, None if OK."""
    if url.startswith("magnet:"):
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return "malformed URL"
    if not parsed.scheme:
        return "URL must include a scheme (http://, https://, ftp://, magnet:)"
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        return f"URL scheme '{parsed.scheme}' not allowed (use http, https, ftp, or magnet)"
    if parsed.scheme.lower() in {"http", "https", "ftp"} and not parsed.hostname:
        return "URL must include a hostname"
    return None


def _validate_output_path(output: str) -> str | None:
    """Return error message if output path is unsafe, None if OK."""
    if not output:
        return None
    if os.path.isabs(output):
        return "output must be a relative path, not absolute"
    parts = Path(output).parts
    if ".." in parts:
        return "output must not contain '..'"
    if any(p.startswith(".") for p in parts):
        return "output must not contain hidden directories or files"
    try:
        cwd = Path.cwd().resolve()
        resolved = (cwd / output).resolve()
        resolved.relative_to(cwd)
    except (ValueError, OSError):
        return "output path escapes current directory"
    return None


def _parse_add_items(
    payload: object,
) -> tuple[list[dict[str, str | None]] | None, dict[str, object] | None]:
    if not isinstance(payload, dict):
        return None, _error_payload("invalid_payload", "expected a JSON object")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return None, _error_payload("invalid_items", "items must be a non-empty list")

    items: list[dict[str, str | None]] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            return None, _error_payload(
                "invalid_item", f"items[{index}] must be an object", index=index
            )
        url = str(raw_item.get("url", "")).strip()
        if not url:
            return None, _error_payload(
                "invalid_item",
                f"items[{index}].url must be a non-empty string",
                index=index,
            )
        url_error = _validate_url(url)
        if url_error:
            return None, _error_payload(
                "invalid_url",
                f"items[{index}].url: {url_error}",
                index=index,
            )
        output = raw_item.get("output")
        output_value = str(output).strip() if output is not None else ""
        output_error = _validate_output_path(output_value)
        if output_error:
            return None, _error_payload(
                "invalid_output",
                f"items[{index}].output: {output_error}",
                index=index,
            )
        post_action_rule = raw_item.get("post_action_rule")
        post_action_value = (
            str(post_action_rule).strip() if post_action_rule is not None else ""
        )
        mirrors_raw = raw_item.get("mirrors")
        mirrors = None
        if isinstance(mirrors_raw, list):
            mirrors = [str(m).strip() for m in mirrors_raw if str(m).strip()]
            for mi, mirror_url in enumerate(mirrors):
                mirror_error = _validate_url(mirror_url)
                if mirror_error:
                    return None, _error_payload(
                        "invalid_url",
                        f"items[{index}].mirrors[{mi}]: {mirror_error}",
                        index=index,
                    )
        torrent_data = raw_item.get("torrent_data")
        metalink_data = raw_item.get("metalink_data")
        priority_raw = raw_item.get("priority", 0)
        try:
            priority_val = int(priority_raw)
        except (TypeError, ValueError):
            priority_val = 0
        torrent_data_str = None
        if torrent_data:
            torrent_data_str = str(torrent_data)
            try:
                import base64

                base64.b64decode(torrent_data_str, validate=True)
            except Exception:
                return None, _error_payload(
                    "invalid_torrent_data",
                    f"items[{index}].torrent_data must be valid base64",
                    index=index,
                )
        metalink_data_str = None
        if metalink_data:
            metalink_data_str = str(metalink_data)
            try:
                import base64

                base64.b64decode(metalink_data_str, validate=True)
            except Exception:
                return None, _error_payload(
                    "invalid_metalink_data",
                    f"items[{index}].metalink_data must be valid base64",
                    index=index,
                )
        distribute = bool(raw_item.get("distribute", False))
        items.append(
            {
                "url": url,
                "output": output_value or None,
                "post_action_rule": post_action_value or None,
                "mirrors": mirrors,
                "torrent_data": torrent_data_str,
                "metalink_data": metalink_data_str,
                "priority": priority_val,
                "distribute": distribute,
            }
        )
    return items, None


# ── Route handlers ──


def get_status(h: object, parsed: object) -> None:
    query = dict(
        part.split("=", 1) if "=" in part else (part, "")
        for part in parsed.query.split("&")
        if part
    )
    payload = h._status_payload()
    filter_status = query.get("status", "").strip()
    filter_session = query.get("session", "").strip()
    if filter_status or filter_session:
        items = payload.get("items", [])
        if filter_status:
            statuses = set(filter_status.split(","))
            items = [i for i in items if i.get("status") in statuses]
        if filter_session == "current":
            sid = payload.get("state", {}).get("session_id")
            items = [i for i in items if i.get("session_id") == sid]
        elif filter_session:
            items = [i for i in items if i.get("session_id") == filter_session]
        payload = dict(payload)
        payload["items"] = items
        payload["summary"] = summarize_queue(items)
        payload["filtered"] = True
    h._send_json(payload, etag=True)


def get_archive(h: object, parsed: object) -> None:
    query = dict(
        part.split("=", 1) if "=" in part else (part, "")
        for part in parsed.query.split("&")
        if part
    )
    try:
        limit = max(1, min(500, int(query.get("limit", "100"))))
    except ValueError:
        limit = 100
    items = load_archive()
    h._send_json({"items": items[-limit:]})


def get_item_files(h: object, parsed: object) -> None:
    path = urlparse(h.path).path
    item_id = path.split("/")[3]
    if not _validate_item_id(item_id):
        h._send_json(_error_payload("invalid_id", "item ID must be a UUID"), status=400)
        return
    result = api_get_item_files(item_id)
    if not result.get("ok", True):
        status_code = 404 if result.get("error") == "not_found" else 400
        h._send_json(result, status=status_code)
        return
    h._send_json(result)


def post_add(h: object, payload: object, path: str) -> None:
    items, error = _parse_add_items(payload)
    if error is not None:
        h._send_json(error, status=400)
        return
    added = [
        add_queue_item(
            item["url"],
            output=item["output"],
            post_action_rule=item["post_action_rule"],
            mirrors=item.get("mirrors"),
            torrent_data=item.get("torrent_data"),
            metalink_data=item.get("metalink_data"),
            priority=item.get("priority", 0),
            distribute=item.get("distribute", False),
        ).__dict__
        for item in items
    ]
    h._invalidate_status_cache()
    h._send_json({"ok": True, "count": len(added), "added": added})


def post_cleanup(h: object, payload: object, path: str) -> None:
    params = payload if isinstance(payload, dict) else {}
    max_age = int(params.get("max_done_age_days", 7))
    max_count = int(params.get("max_done_count", 100))
    result = auto_cleanup_queue(max_done_age_days=max_age, max_done_count=max_count)
    if result["archived"] > 0:
        h._invalidate_status_cache()
    h._send_json({"ok": True, **result})


def post_item_files(h: object, payload: object, path: str) -> None:
    item_id = path.split("/")[3]
    if not _validate_item_id(item_id):
        h._send_json(_error_payload("invalid_id", "item ID must be a UUID"), status=400)
        return
    select = payload.get("select") if isinstance(payload, dict) else None
    if not isinstance(select, list) or not select:
        h._send_json(
            _error_payload("invalid_payload", "expected {select: [1, 3, 5]}"),
            status=400,
        )
        return
    try:
        indices = [int(i) for i in select]
    except (ValueError, TypeError):
        h._send_json(
            _error_payload("invalid_payload", "select must be a list of integers"),
            status=400,
        )
        return
    result = select_item_files(item_id, indices)
    if not result.get("ok", True):
        status_code = 404 if result.get("error") == "not_found" else 400
        h._send_json(result, status=status_code)
        return
    h._invalidate_status_cache()
    h._send_json(result)


def post_item_action(h: object, payload: object, path: str) -> None:
    parts = path.split("/")
    item_id = parts[3]
    if not _validate_item_id(item_id):
        h._send_json(_error_payload("invalid_id", "item ID must be a UUID"), status=400)
        return
    action = parts[4]
    if action == "priority":
        p = payload.get("priority") if isinstance(payload, dict) else None
        if p is None:
            h._send_json(
                _error_payload("invalid_payload", "expected {priority: N}"),
                status=400,
            )
            return
        try:
            pval = int(p)
        except (TypeError, ValueError):
            h._send_json(
                _error_payload("invalid_payload", "priority must be an integer"),
                status=400,
            )
            return
        from ..queue_ops import set_item_priority

        result = set_item_priority(item_id, pval)
        if not result.get("ok", True):
            h._send_json(
                result, status=404 if result.get("error") == "not_found" else 400
            )
            return
        h._invalidate_status_cache()
        h._send_json(result)
        return
    item_actions = {
        "pause": pause_queue_item,
        "resume": resume_queue_item,
        "remove": remove_queue_item,
        "retry": retry_queue_item,
    }
    handler = item_actions.get(action)
    if handler is None:
        h._send_json(
            _error_payload("invalid_action", f"unknown item action: {action}"),
            status=400,
        )
        return
    try:
        result = handler(item_id)
    except Exception:
        h._send_json(_error_payload("internal_error", "internal error"), status=500)
        return
    if not result.get("ok", True):
        status_code = 404 if result.get("error") == "not_found" else 400
        h._send_json(result, status=status_code)
        return
    h._invalidate_status_cache()
    h._send_json(result)
