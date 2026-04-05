from __future__ import annotations

import json
import os
import queue
import subprocess
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .api import (
    add_queue_item,
    bandwidth_status,
    aria2_change_options,
    aria2_tell_active,
    active_status,
    homebrew_install_ariaflow,
    homebrew_uninstall_ariaflow,
    install_aria2_launchd,
    auto_cleanup_queue,
    get_item_files as api_get_item_files,
    load_archive,
    load_session_history,
    manual_probe,
    load_action_log,
    load_declaration,
    load_queue,
    load_state,
    pause_active_transfer,
    pause_queue_item,
    record_action,
    remove_queue_item,
    resume_active_transfer,
    resume_queue_item,
    retry_queue_item,
    select_item_files,
    session_stats,
    run_ucc,
    save_declaration,
    start_new_state_session,
    status_all,
    stop_background_process,
    summarize_queue,
    uninstall_aria2_launchd,
    ucc_record,
)

# ── Helper functions ──

_ALLOWED_URL_SCHEMES = {"http", "https", "ftp", "magnet"}


def _error_payload(error: str, message: str, **detail: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": False,
        "error": error,
        "message": message,
    }
    payload.update(detail)
    return payload


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
    if ".." in output.split(os.sep) or ".." in output.split("/"):
        return "output must not contain '..'"
    try:
        resolved = Path(output).resolve()
        cwd = Path.cwd().resolve()
        if not str(resolved).startswith(str(cwd)):
            return "output path escapes current directory"
    except (ValueError, OSError):
        return "output path is invalid"
    return None


def _validate_item_id(item_id: str) -> bool:
    """Check item_id looks like a UUID."""
    import re
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", item_id))


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


def _session_fields() -> dict[str, object]:
    state = load_state()
    return {
        "session_id": state.get("session_id"),
        "session_started_at": state.get("session_started_at"),
        "session_last_seen_at": state.get("session_last_seen_at"),
        "session_closed_at": state.get("session_closed_at"),
        "session_closed_reason": state.get("session_closed_reason"),
    }


def _lifecycle_payload() -> dict[str, object]:
    lifecycle = status_all()
    lifecycle.update(_session_fields())
    return lifecycle


def _find_openapi_spec() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent / "openapi.yaml",
        Path(__file__).resolve().parent.parent.parent
        / "openapi.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _api_discovery() -> dict[str, object]:
    return {
        "name": "ariaflow",
        "version": __version__,
        "docs": "/api/docs",
        "openapi": "/api/openapi.yaml",
        "endpoints": {
            "GET": [
                {"path": "/api", "description": "API discovery (this endpoint)"},
                {
                    "path": "/api/scheduler",
                    "description": "Scheduler state (idle/running/paused/stopping)",
                },
                {
                    "path": "/api/status",
                    "description": "Queue items, state, summary",
                    "params": "?status=queued,paused&session=current",
                },
                {
                    "path": "/api/bandwidth",
                    "description": "Bandwidth status, config, last probe",
                },
                {
                    "path": "/api/log",
                    "description": "Action log entries",
                    "params": "?limit=120",
                },
                {
                    "path": "/api/declaration",
                    "description": "UIC declaration (gates, preferences)",
                },
                {"path": "/api/options", "description": "Alias for /api/declaration"},
                {"path": "/api/lifecycle", "description": "Install/service status"},
                {
                    "path": "/api/downloads/{id}/files",
                    "description": "List torrent/metalink files",
                },
                {"path": "/api/docs", "description": "Swagger UI"},
                {"path": "/api/openapi.yaml", "description": "OpenAPI 3.0 spec"},
                {"path": "/api/tests", "description": "Run test suite"},
                {
                    "path": "/api/events",
                    "description": "Server-Sent Events stream (real-time state changes)",
                },
                {
                    "path": "/api/downloads/archive",
                    "description": "Archived (removed/old) items",
                    "params": "?limit=100",
                },
                {
                    "path": "/api/sessions",
                    "description": "Session history",
                    "params": "?limit=50",
                },
                {
                    "path": "/api/sessions/stats",
                    "description": "Per-session statistics",
                    "params": "?session_id=...",
                },
            ],
            "POST": [
                {"path": "/api/downloads/add", "description": "Enqueue URLs"},
                {"path": "/api/scheduler/start", "description": "Start queue processor"},
                {"path": "/api/scheduler/stop", "description": "Stop queue processor"},
                {"path": "/api/scheduler/preflight", "description": "Run preflight checks"},
                {"path": "/api/scheduler/ucc", "description": "Execute UCC cycle"},
                {"path": "/api/scheduler/pause", "description": "Pause all active transfers"},
                {"path": "/api/scheduler/resume", "description": "Resume all paused transfers"},
                {"path": "/api/sessions/new", "description": "Create new session"},
                {"path": "/api/declaration", "description": "Save UIC declaration"},
                {
                    "path": "/api/bandwidth/probe",
                    "description": "Run bandwidth probe manually",
                },
                {
                    "path": "/api/downloads/cleanup",
                    "description": "Archive stale done/error items",
                },
                {
                    "path": "/api/aria2/change_global_option",
                    "description": "Change aria2 global options (3-tier safety)",
                },
                {"path": "/api/downloads/{id}/pause", "description": "Pause a queue item"},
                {
                    "path": "/api/downloads/{id}/resume",
                    "description": "Resume a paused item",
                },
                {"path": "/api/downloads/{id}/remove", "description": "Remove a queue item"},
                {"path": "/api/downloads/{id}/retry", "description": "Retry a failed item"},
                {
                    "path": "/api/downloads/{id}/files",
                    "description": "Select torrent/metalink files",
                },
                {
                    "path": "/api/lifecycle/{target}/{action}",
                    "description": "Install/uninstall components (macOS)",
                },
            ],
        },
    }


def _swagger_ui_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ariaflow API Docs</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({
  url: '/api/openapi.yaml',
  dom_id: '#swagger-ui',
  deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
  layout: 'BaseLayout'
});
</script>
</body>
</html>"""


def _run_tests() -> dict[str, object]:
    from . import webapp as _wa
    project_root = Path(__file__).resolve().parent.parent.parent
    try:
        result = _wa.subprocess.run(
            ["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
        lines = (result.stderr or "").strip().splitlines()
        tests: list[dict[str, str]] = []
        summary = ""
        for line in lines:
            if " ... " in line:
                name, _, status = line.rpartition(" ... ")
                tests.append({"name": name.strip(), "status": status.strip()})
            elif (
                line.startswith("Ran ")
                or line.startswith("OK")
                or line.startswith("FAILED")
            ):
                summary += line + "\n"
        passed = sum(1 for t in tests if t["status"] == "ok")
        failed = sum(1 for t in tests if t["status"] != "ok")
        return {
            "ok": result.returncode == 0,
            "total": len(tests),
            "passed": passed,
            "failed": failed,
            "tests": tests,
            "summary": summary.strip(),
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "message": "tests timed out after 60s"}
    except Exception as exc:
        return {"ok": False, "error": "execution_error", "message": str(exc)}


# ── GET route handlers ──

def get_health(h: object, parsed: object) -> None:
    h._send_json({"status": "ok", "version": __version__})


def get_openapi_yaml(h: object, parsed: object) -> None:
    spec_path = _find_openapi_spec()
    if spec_path is None:
        h._send_json(
            _error_payload("not_found", "openapi.yaml not found"),
            status=404,
        )
        return
    body = spec_path.read_bytes()
    h.send_response(HTTPStatus.OK)
    h.send_header("Content-Type", "text/yaml; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()
    h.wfile.write(body)


def get_docs(h: object, parsed: object) -> None:
    html = _swagger_ui_html()
    body = html.encode("utf-8")
    h.send_response(HTTPStatus.OK)
    h.send_header("Content-Type", "text/html; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def get_tests(h: object, parsed: object) -> None:
    result = _run_tests()
    h._send_json(result)


def get_api(h: object, parsed: object) -> None:
    h._send_json(_api_discovery())


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


def get_events(h: object, parsed: object) -> None:
    from .webapp import _sse_subscribe, _sse_unsubscribe, API_SCHEMA_VERSION
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("X-Schema-Version", API_SCHEMA_VERSION)
    h.end_headers()
    q = _sse_subscribe()
    try:
        init = json.dumps(
            {
                "schema_version": API_SCHEMA_VERSION,
                "server_version": __version__,
            },
            sort_keys=True,
        )
        h.wfile.write(f"event: connected\ndata: {init}\n\n".encode())
        h.wfile.flush()
        while True:
            try:
                msg = q.get(timeout=30)
                h.wfile.write(msg.encode())
                h.wfile.flush()
            except queue.Empty:
                h.wfile.write(b": keepalive\n\n")
                h.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        _sse_unsubscribe(q)


def get_bandwidth(h: object, parsed: object) -> None:
    h._send_json(bandwidth_status())


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


def get_log(h: object, parsed: object) -> None:
    limit = 120
    query = dict(
        part.split("=", 1) if "=" in part else (part, "")
        for part in parsed.query.split("&")
        if part
    )
    try:
        limit = max(1, min(500, int(query.get("limit", "120"))))
    except ValueError:
        limit = 120
    h._send_json({"items": load_action_log(limit=limit)})


def get_torrents(h: object, parsed: object) -> None:
    items = load_queue()
    seeds = []
    for item in items:
        if item.get("distribute_status") == "seeding" and item.get("distribute_infohash"):
            seeds.append({
                "infohash": item["distribute_infohash"],
                "name": item.get("output") or item.get("url", "").split("/")[-1].split("?")[0],
                "url": item.get("url"),
                "seed_gid": item.get("distribute_seed_gid"),
                "torrent_url": f"/api/torrents/{item['distribute_infohash']}.torrent",
                "started_at": item.get("distribute_started_at"),
                "item_id": item.get("id"),
            })
    h._send_json({"torrents": seeds, "count": len(seeds)})


def get_declaration(h: object, parsed: object) -> None:
    h._send_json(load_declaration())


def get_aria2_global_option(h: object, parsed: object) -> None:
    from .aria2_rpc import aria2_current_global_options
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
        from .core import aria2_get_option
        result = aria2_get_option(gid)
        h._send_json(result)
    except Exception as exc:
        h._send_json(
            _error_payload("rpc_error", "internal error"),
            status=500,
        )


def get_aria2_option_tiers(h: object, parsed: object) -> None:
    from .aria2_rpc import _MANAGED_ARIA2_OPTIONS, _SAFE_ARIA2_OPTIONS
    from .core import _pref_value

    h._send_json({
        "managed": sorted(_MANAGED_ARIA2_OPTIONS),
        "safe": sorted(_SAFE_ARIA2_OPTIONS),
        "unsafe_enabled": bool(_pref_value("aria2_unsafe_options", False)),
    })


def get_lifecycle(h: object, parsed: object) -> None:
    h._send_json(_lifecycle_payload())


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


def get_torrent_file(h: object, parsed: object) -> None:
    path = urlparse(h.path).path
    infohash = path.split("/")[-1].removesuffix(".torrent")
    items = load_queue()
    for item in items:
        if item.get("distribute_infohash") == infohash:
            torrent_path = item.get("distribute_torrent_path")
            if torrent_path and Path(torrent_path).is_file():
                body = Path(torrent_path).read_bytes()
                h.send_response(HTTPStatus.OK)
                h.send_header("Content-Type", "application/x-bittorrent")
                h.send_header("Content-Length", str(len(body)))
                h.send_header("Access-Control-Allow-Origin", "*")
                h.end_headers()
                h.wfile.write(body)
                return
    h._send_json(_error_payload("not_found", "torrent not found"), status=404)


# ── POST route handlers ──

def post_bandwidth_probe(h: object, payload: object, path: str) -> None:
    result = manual_probe()
    h._invalidate_status_cache()
    h._send_json(result)


def post_cleanup(h: object, payload: object, path: str) -> None:
    params = payload if isinstance(payload, dict) else {}
    max_age = int(params.get("max_done_age_days", 7))
    max_count = int(params.get("max_done_count", 100))
    result = auto_cleanup_queue(
        max_done_age_days=max_age, max_done_count=max_count
    )
    if result["archived"] > 0:
        h._invalidate_status_cache()
    h._send_json({"ok": True, **result})


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


def post_preflight(h: object, payload: object, path: str) -> None:
    from . import webapp as _wa
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


def post_scheduler_start(h: object, payload: object, path: str) -> None:
    if not isinstance(payload, dict):
        payload = {}
    before = {"state": load_state(), "queue": summarize_queue(load_queue())}
    from . import webapp as _wa
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


def post_declaration(h: object, payload: object, path: str) -> None:
    declaration = payload if isinstance(payload, dict) else {}
    saved = save_declaration(declaration)
    h._invalidate_status_cache()
    h._send_json({"saved": True, "declaration": saved})


def post_lifecycle_action(h: object, payload: object, path: str) -> None:
    from . import webapp as _wa
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


def post_pause(h: object, payload: object, path: str) -> None:
    result = pause_active_transfer()
    h._invalidate_status_cache()
    h._send_json(result)


def post_resume(h: object, payload: object, path: str) -> None:
    result = resume_active_transfer()
    h._invalidate_status_cache()
    h._send_json(result)


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


def post_torrent_stop(h: object, payload: object, path: str) -> None:
    """Stop seeding a specific torrent by infohash."""
    if not isinstance(payload, dict):
        h._send_json(_error_payload("invalid_payload", "expected {infohash}"), status=400)
        return
    infohash = str(payload.get("infohash", "")).strip()
    if not infohash:
        h._send_json(_error_payload("invalid_payload", "infohash required"), status=400)
        return
    from .core import load_queue, save_queue, aria2_remove, record_action
    items = load_queue()
    found = False
    for item in items:
        if item.get("distribute_infohash") == infohash and item.get("distribute_status") == "seeding":
            seed_gid = item.get("distribute_seed_gid")
            if seed_gid:
                try:
                    aria2_remove(seed_gid)
                except Exception:
                    pass
            torrent_path = item.get("distribute_torrent_path")
            if torrent_path:
                try:
                    import os
                    os.remove(torrent_path)
                except Exception:
                    pass
            item["distribute_status"] = "stopped"
            item.pop("distribute_seed_gid", None)
            found = True
            record_action(
                action="seed_stopped",
                target="queue_item",
                outcome="changed",
                reason="user_stop_seed",
                before={},
                after={"item_id": item.get("id"), "infohash": infohash},
                detail={"item_id": item.get("id"), "infohash": infohash},
            )
            break
    if found:
        save_queue(items)
        h._invalidate_status_cache()
        h._send_json({"ok": True, "infohash": infohash, "status": "stopped"})
    else:
        h._send_json(_error_payload("not_found", f"no active seed for {infohash}"), status=404)


def post_aria2_set_limits(h: object, payload: object, path: str) -> None:
    """Set managed bandwidth/seed options via dedicated functions."""
    if not isinstance(payload, dict):
        h._send_json(
            _error_payload("invalid_payload", "expected JSON object"),
            status=400,
        )
        return
    from .core import (
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
        from .core import aria2_change_option
        aria2_change_option(gid, {str(k): str(v) for k, v in options.items()})
        h._send_json({"ok": True, "gid": gid, "applied": options})
    except Exception:
        h._send_json(
            _error_payload("rpc_error", "internal error"),
            status=500,
        )


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
            _error_payload(
                "invalid_payload", "select must be a list of integers"
            ),
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
        from .queue_ops import set_item_priority
        result = set_item_priority(item_id, pval)
        if not result.get("ok", True):
            h._send_json(result, status=404 if result.get("error") == "not_found" else 400)
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
    except Exception as exc:
        h._send_json(_error_payload("internal_error", "internal error"), status=500)
        return
    if not result.get("ok", True):
        status_code = 404 if result.get("error") == "not_found" else 400
        h._send_json(result, status=status_code)
        return
    h._invalidate_status_cache()
    h._send_json(result)


# ── PATCH route handlers ──

def patch_declaration_preferences(h: object, payload: object) -> None:
    if not isinstance(payload, dict) or not payload:
        h._send_json(
            _error_payload("invalid_payload", "expected {preference_name: value}"),
            status=400,
        )
        return
    from .core import load_declaration, save_declaration, record_action, storage_locked
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
