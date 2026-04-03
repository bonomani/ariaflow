from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from uuid import uuid4

import subprocess
from pathlib import Path

from . import __version__
from .api import (
    add_queue_item,
    bandwidth_status,
    aria2_change_options,
    aria2_tell_active,
    active_status,
    auto_preflight_on_run,
    aria2_status,
    aria2_current_bandwidth,
    homebrew_install_ariaflow,
    homebrew_uninstall_ariaflow,
    install_aria2_launchd,
    is_macos,
    auto_cleanup_queue,
    get_item_files,
    load_archive,
    load_session_history,
    manual_probe,
    load_action_log,
    load_declaration,
    load_queue,
    load_state,
    pause_active_transfer,
    pause_queue_item,
    preflight,
    record_action,
    remove_queue_item,
    resume_active_transfer,
    resume_queue_item,
    retry_queue_item,
    select_item_files,
    session_stats,
    run_ucc,
    save_declaration,
    start_background_process,
    start_new_state_session,
    status_all,
    stop_background_process,
    summarize_queue,
    uninstall_aria2_launchd,
    ucc_record,
)
from .core import cleanup_queue_state

STATUS_CACHE: dict[str, object] = {"ts": 0.0, "payload": None}
STATUS_CACHE_TTL = 2.0
API_SCHEMA_VERSION = "2"

# ── SSE event bus ──
_sse_clients: list[queue.Queue[str]] = []
_sse_lock = threading.Lock()


def _sse_publish(event: str, data: dict[str, object]) -> None:
    msg = f"event: {event}\ndata: {json.dumps(data, sort_keys=True)}\n\n"
    with _sse_lock:
        dead: list[queue.Queue[str]] = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


def _sse_subscribe() -> queue.Queue[str]:
    q: queue.Queue[str] = queue.Queue(maxsize=64)
    with _sse_lock:
        _sse_clients.append(q)
    return q


def _sse_unsubscribe(q: queue.Queue[str]) -> None:
    with _sse_lock:
        if q in _sse_clients:
            _sse_clients.remove(q)


def _error_payload(error: str, message: str, **detail: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": False,
        "error": error,
        "message": message,
    }
    payload.update(detail)
    return payload


_ALLOWED_URL_SCHEMES = {"http", "https", "ftp", "magnet"}


def _validate_url(url: str) -> str | None:
    """Return error message if URL is unsafe, None if OK."""
    if url.startswith("magnet:"):
        return None  # magnet links have no scheme in urlparse
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
        items.append(
            {
                "url": url,
                "output": output_value or None,
                "post_action_rule": post_action_value or None,
                "mirrors": mirrors,
                "torrent_data": torrent_data_str,
                "metalink_data": metalink_data_str,
                "priority": priority_val,
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
        Path(__file__).resolve().parent / "openapi.yaml",  # package data
        Path(__file__).resolve().parent.parent.parent
        / "openapi.yaml",  # dev source tree
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
                    "path": "/api/item/{id}/files",
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
                    "path": "/api/archive",
                    "description": "Archived (removed/old) items",
                    "params": "?limit=100",
                },
                {
                    "path": "/api/sessions",
                    "description": "Session history",
                    "params": "?limit=50",
                },
                {
                    "path": "/api/session/stats",
                    "description": "Per-session statistics",
                    "params": "?session_id=...",
                },
            ],
            "POST": [
                {"path": "/api/add", "description": "Enqueue URLs"},
                {"path": "/api/run", "description": "Start/stop queue processor"},
                {"path": "/api/preflight", "description": "Run preflight checks"},
                {"path": "/api/ucc", "description": "Execute UCC cycle"},
                {"path": "/api/pause", "description": "Pause all active transfers"},
                {"path": "/api/resume", "description": "Resume all paused transfers"},
                {"path": "/api/session", "description": "Create new session"},
                {"path": "/api/declaration", "description": "Save UIC declaration"},
                {
                    "path": "/api/bandwidth/probe",
                    "description": "Run bandwidth probe manually",
                },
                {
                    "path": "/api/cleanup",
                    "description": "Archive stale done/error items",
                },
                {
                    "path": "/api/aria2/options",
                    "description": "Change aria2 global options (safe subset)",
                },
                {"path": "/api/item/{id}/pause", "description": "Pause a queue item"},
                {
                    "path": "/api/item/{id}/resume",
                    "description": "Resume a paused item",
                },
                {"path": "/api/item/{id}/remove", "description": "Remove a queue item"},
                {"path": "/api/item/{id}/retry", "description": "Retry a failed item"},
                {
                    "path": "/api/item/{id}/files",
                    "description": "Select torrent/metalink files",
                },
                {
                    "path": "/api/lifecycle/action",
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
    project_root = Path(__file__).resolve().parent.parent.parent
    try:
        result = subprocess.run(
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


class AriaFlowHandler(BaseHTTPRequestHandler):
    _GET_ROUTES: dict[str, str] = {
        "/api/health": "_get_health",
        "/api/openapi.yaml": "_get_openapi_yaml",
        "/api/docs": "_get_docs",
        "/api/tests": "_get_tests",
        "/api": "_get_api",
        "/api/scheduler": "_get_scheduler",
        "/api/events": "_get_events",
        "/api/bandwidth": "_get_bandwidth",
        "/api/status": "_get_status",
        "/api/log": "_get_log",
        "/api/declaration": "_get_declaration",
        "/api/options": "_get_options",
        "/api/lifecycle": "_get_lifecycle",
        "/api/archive": "_get_archive",
        "/api/sessions": "_get_sessions",
        "/api/session/stats": "_get_session_stats",
    }

    _POST_ROUTES: dict[str, str] = {
        "/api/bandwidth/probe": "_post_bandwidth_probe",
        "/api/cleanup": "_post_cleanup",
        "/api/add": "_post_add",
        "/api/preflight": "_post_preflight",
        "/api/run": "_post_run",
        "/api/ucc": "_post_ucc",
        "/api/declaration": "_post_declaration",
        "/api/lifecycle/action": "_post_lifecycle_action",
        "/api/session": "_post_session",
        "/api/pause": "_post_pause",
        "/api/resume": "_post_resume",
        "/api/aria2/options": "_post_aria2_options",
    }

    def _invalidate_status_cache(self, event: str = "state_changed") -> None:
        STATUS_CACHE["ts"] = 0.0
        STATUS_CACHE["payload"] = None
        state = load_state()
        _sse_publish(
            event,
            {"rev": state.get("_rev", 0), "server_version": __version__},
        )

    def _status_payload(self, force: bool = False) -> dict:
        now = time.time()
        cached = STATUS_CACHE.get("payload")
        if (
            not force
            and cached is not None
            and now - float(STATUS_CACHE.get("ts", 0.0)) < STATUS_CACHE_TTL
        ):
            return cached  # type: ignore[return-value]

        try:
            cleanup_queue_state()
        except Exception:
            pass

        state = load_state()
        items = load_queue()
        bandwidth = aria2_current_bandwidth(timeout=3)
        payload = {
            "items": items,
            "state": state,
            "summary": summarize_queue(items),
            "aria2": aria2_status(timeout=3),
            "bandwidth": bandwidth,
            "_rev": state.get("_rev", 0),
            "ariaflow": {
                "reachable": True,
                "version": __version__,
                "schema_version": API_SCHEMA_VERSION,
                "pid": os.getpid(),
            },
        }
        active = active_status(timeout=3)
        if active:
            payload["active"] = active
        actives = aria2_tell_active(timeout=3)
        if actives:
            payload["actives"] = actives
        STATUS_CACHE["ts"] = now
        STATUS_CACHE["payload"] = payload
        return payload

    def _send_json(
        self, payload: dict, status: int = 200, *, etag: bool = False
    ) -> None:
        request_id = str(uuid4())
        payload.setdefault("_schema", API_SCHEMA_VERSION)
        payload.setdefault("_request_id", request_id)
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        if etag:
            tag = '"' + hashlib.md5(body).hexdigest() + '"'
            if_none = self.headers.get("If-None-Match", "")
            if if_none == tag:
                self.send_response(304)
                self.send_header("ETag", tag)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Request-Id", request_id)
        self.send_header("X-Schema-Version", API_SCHEMA_VERSION)
        if etag:
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, If-None-Match",
        )
        self.send_header(
            "Access-Control-Expose-Headers",
            "ETag, X-Request-Id, X-Schema-Version",
        )
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        # Special routes (redirect, non-API)
        if path in {"/", "/index.html"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/api/docs")
            self.end_headers()
            return
        if path in {"/bandwidth", "/lifecycle", "/options", "/log"}:
            self._send_json(
                _error_payload("ui_not_served", "ariaflow is API-only; use ariaflow-web for the dashboard"),
                status=400,
            )
            return
        # Parameterized route: /api/item/{id}/files
        if path.startswith("/api/item/") and path.endswith("/files") and path.count("/") == 4:
            self._get_item_files(parsed)
            return
        # Dispatch table
        method_name = self._GET_ROUTES.get(path)
        if method_name:
            getattr(self, method_name)(parsed)
        else:
            self._send_json(_error_payload("not_found", "resource not found"), status=404)

    def _get_health(self, parsed: object) -> None:
        self._send_json({"status": "ok", "version": __version__})

    def _get_openapi_yaml(self, parsed: object) -> None:
        spec_path = _find_openapi_spec()
        if spec_path is None:
            self._send_json(
                {"error": "not_found", "message": "openapi.yaml not found"},
                status=404,
            )
            return
        body = spec_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/yaml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _get_docs(self, parsed: object) -> None:
        html = _swagger_ui_html()
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_tests(self, parsed: object) -> None:
        result = _run_tests()
        self._send_json(result)

    def _get_api(self, parsed: object) -> None:
        self._send_json(_api_discovery())

    def _get_scheduler(self, parsed: object) -> None:
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
        self._send_json(
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

    def _get_events(self, parsed: object) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Schema-Version", API_SCHEMA_VERSION)
        self.end_headers()
        q = _sse_subscribe()
        try:
            # send initial state
            init = json.dumps(
                {
                    "schema_version": API_SCHEMA_VERSION,
                    "server_version": __version__,
                },
                sort_keys=True,
            )
            self.wfile.write(f"event: connected\ndata: {init}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=30)
                    self.wfile.write(msg.encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            _sse_unsubscribe(q)

    def _get_bandwidth(self, parsed: object) -> None:
        self._send_json(bandwidth_status())

    def _get_status(self, parsed: object) -> None:
        query = dict(
            part.split("=", 1) if "=" in part else (part, "")
            for part in parsed.query.split("&")
            if part
        )
        payload = self._status_payload()
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
        self._send_json(payload, etag=True)

    def _get_log(self, parsed: object) -> None:
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
        self._send_json({"items": load_action_log(limit=limit)})

    def _get_declaration(self, parsed: object) -> None:
        self._send_json(load_declaration())

    def _get_options(self, parsed: object) -> None:
        self._send_json(load_declaration())

    def _get_lifecycle(self, parsed: object) -> None:
        self._send_json(_lifecycle_payload())

    def _get_item_files(self, parsed: object) -> None:
        path = urlparse(self.path).path
        item_id = path.split("/")[3]
        if not _validate_item_id(item_id):
            self._send_json(_error_payload("invalid_id", "item ID must be a UUID"), status=400)
            return
        result = get_item_files(item_id)
        if not result.get("ok", True):
            status_code = 404 if result.get("error") == "not_found" else 400
            self._send_json(result, status=status_code)
            return
        self._send_json(result)

    def _get_archive(self, parsed: object) -> None:
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
        self._send_json({"items": items[-limit:]})

    def _get_sessions(self, parsed: object) -> None:
        query = dict(
            part.split("=", 1) if "=" in part else (part, "")
            for part in parsed.query.split("&")
            if part
        )
        try:
            limit = max(1, min(200, int(query.get("limit", "50"))))
        except ValueError:
            limit = 50
        self._send_json({"sessions": load_session_history(limit=limit)})

    def _get_session_stats(self, parsed: object) -> None:
        query = dict(
            part.split("=", 1) if "=" in part else (part, "")
            for part in parsed.query.split("&")
            if part
        )
        sid = query.get("session_id") or None
        self._send_json(session_stats(session_id=sid))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send_json(
                _error_payload("invalid_json", "request body must be valid JSON"),
                status=400,
            )
            return

        # Parameterized route: /api/item/{id}/files (POST)
        if (
            path.startswith("/api/item/")
            and path.endswith("/files")
            and path.count("/") == 4
        ):
            self._post_item_files(payload, path)
            return

        # Parameterized route: /api/item/{id}/{action}
        if path.startswith("/api/item/") and path.count("/") == 4:
            self._post_item_action(payload, path)
            return

        # Dispatch table
        method_name = self._POST_ROUTES.get(path)
        if method_name:
            getattr(self, method_name)(payload, path)
        else:
            self._send_json(_error_payload("not_found", "resource not found"), status=404)

    def _post_bandwidth_probe(self, payload: object, path: str) -> None:
        result = manual_probe()
        self._invalidate_status_cache()
        self._send_json(result)

    def _post_cleanup(self, payload: object, path: str) -> None:
        params = payload if isinstance(payload, dict) else {}
        max_age = int(params.get("max_done_age_days", 7))
        max_count = int(params.get("max_done_count", 100))
        result = auto_cleanup_queue(
            max_done_age_days=max_age, max_done_count=max_count
        )
        if result["archived"] > 0:
            self._invalidate_status_cache()
        self._send_json({"ok": True, **result})

    def _post_add(self, payload: object, path: str) -> None:
        items, error = _parse_add_items(payload)
        if error is not None:
            self._send_json(error, status=400)
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
            ).__dict__
            for item in items
        ]
        self._invalidate_status_cache()
        self._send_json({"ok": True, "count": len(added), "added": added})

    def _post_preflight(self, payload: object, path: str) -> None:
        before = {"state": load_state(), "queue": summarize_queue(load_queue())}
        result = preflight()
        result["aria2"] = aria2_status()
        result["bandwidth"] = aria2_current_bandwidth()
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
        self._invalidate_status_cache()
        self._send_json(result)

    def _post_run(self, payload: object, path: str) -> None:
        if not isinstance(payload, dict):
            self._send_json(
                _error_payload("invalid_payload", "expected a JSON object"),
                status=400,
            )
            return
        action = str(payload.get("action", "")).strip().lower()
        if action not in {"start", "stop"}:
            self._send_json(
                _error_payload(
                    "invalid_action",
                    "action must be 'start' or 'stop'",
                    action=action or None,
                ),
                status=400,
            )
            return
        before = {"state": load_state(), "queue": summarize_queue(load_queue())}
        effective_auto_preflight: bool | None = None
        if action == "stop":
            result = stop_background_process()
            response: dict[str, object] = {
                "ok": True,
                "action": "stop",
                "result": result,
            }
        else:
            override, override_error = _resolve_auto_preflight_override(payload)
            if override_error is not None:
                self._send_json(override_error, status=400)
                return
            effective_auto_preflight = (
                auto_preflight_on_run() if override is None else override
            )
            if effective_auto_preflight:
                preflight_result = preflight()
                record_action(
                    action="preflight",
                    target="system",
                    outcome="converged"
                    if preflight_result.get("status") == "pass"
                    else "blocked",
                    reason=preflight_result.get("status", "unknown"),
                    before=before,
                    after={
                        "state": load_state(),
                        "queue": summarize_queue(load_queue()),
                        "preflight": preflight_result,
                    },
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
                        after={
                            "state": load_state(),
                            "queue": summarize_queue(load_queue()),
                            "scheduler": blocked,
                        },
                        detail=blocked,
                    )
                    self._invalidate_status_cache()
                    self._send_json(blocked, status=409)
                    return
            result = start_background_process()
            response = {
                "ok": True,
                "action": "start",
                "effective_auto_preflight_on_run": effective_auto_preflight,
                "result": result,
            }
        record_action(
            action="run",
            target="queue",
            outcome="changed"
            if result.get("started") or result.get("stopped")
            else "unchanged",
            reason=result.get("reason", "unknown"),
            before=before,
            after={
                "state": load_state(),
                "queue": summarize_queue(load_queue()),
                "scheduler": response,
            },
            detail=response,
        )
        self._invalidate_status_cache()
        self._send_json(response)

    def _post_ucc(self, payload: object, path: str) -> None:
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
        self._invalidate_status_cache()
        self._send_json(result)

    def _post_declaration(self, payload: object, path: str) -> None:
        declaration = payload if isinstance(payload, dict) else {}
        saved = save_declaration(declaration)
        self._invalidate_status_cache()
        self._send_json({"saved": True, "declaration": saved})

    def _post_lifecycle_action(self, payload: object, path: str) -> None:
        if not is_macos():
            self._send_json(_error_payload("macos_only", "this endpoint requires macOS"), status=400)
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
                self._send_json(
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
            self._invalidate_status_cache()
            self._send_json(
                {"error": "lifecycle_action_failed", "message": "internal error"},
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
        self._invalidate_status_cache()
        self._send_json(
            {
                "ok": True,
                "target": target,
                "action": action,
                "lifecycle": _lifecycle_payload(),
                "result": result,
            }
        )

    def _post_session(self, payload: object, path: str) -> None:
        action = str(payload.get("action", "")).strip()
        if action != "new":
            self._send_json(
                _error_payload("unsupported_action", f"unknown action: {action}"), status=400
            )
            return
        before = {"state": load_state(), "queue": summarize_queue(load_queue())}
        state = start_new_state_session(reason="manual_new_session")
        self._invalidate_status_cache()
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
        self._send_json(result)

    def _post_pause(self, payload: object, path: str) -> None:
        result = pause_active_transfer()
        self._invalidate_status_cache()
        self._send_json(result)

    def _post_resume(self, payload: object, path: str) -> None:
        result = resume_active_transfer()
        self._invalidate_status_cache()
        self._send_json(result)

    def _post_aria2_options(self, payload: object, path: str) -> None:
        if not isinstance(payload, dict) or not payload:
            self._send_json(
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
            self._send_json(result, status=400)
            return
        self._send_json(result)

    def _post_item_files(self, payload: object, path: str) -> None:
        item_id = path.split("/")[3]
        if not _validate_item_id(item_id):
            self._send_json(_error_payload("invalid_id", "item ID must be a UUID"), status=400)
            return
        select = payload.get("select") if isinstance(payload, dict) else None
        if not isinstance(select, list) or not select:
            self._send_json(
                _error_payload("invalid_payload", "expected {select: [1, 3, 5]}"),
                status=400,
            )
            return
        try:
            indices = [int(i) for i in select]
        except (ValueError, TypeError):
            self._send_json(
                _error_payload(
                    "invalid_payload", "select must be a list of integers"
                ),
                status=400,
            )
            return
        result = select_item_files(item_id, indices)
        if not result.get("ok", True):
            status_code = 404 if result.get("error") == "not_found" else 400
            self._send_json(result, status=status_code)
            return
        self._invalidate_status_cache()
        self._send_json(result)

    def _post_item_action(self, payload: object, path: str) -> None:
        parts = path.split("/")
        item_id = parts[3]
        if not _validate_item_id(item_id):
            self._send_json(_error_payload("invalid_id", "item ID must be a UUID"), status=400)
            return
        action = parts[4]
        item_actions = {
            "pause": pause_queue_item,
            "resume": resume_queue_item,
            "remove": remove_queue_item,
            "retry": retry_queue_item,
        }
        handler = item_actions.get(action)
        if handler is None:
            self._send_json(
                _error_payload("invalid_action", f"unknown item action: {action}"),
                status=400,
            )
            return
        try:
            result = handler(item_id)
        except Exception as exc:
            self._send_json(_error_payload("internal_error", "internal error"), status=500)
            return
        if not result.get("ok", True):
            status_code = 404 if result.get("error") == "not_found" else 400
            self._send_json(result, status=status_code)
            return
        self._invalidate_status_cache()
        self._send_json(result)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), AriaFlowHandler)
