from __future__ import annotations

import json
import queue
import subprocess
from http import HTTPStatus
from pathlib import Path

from .. import __version__
from .helpers import _error_payload


# ── Single-use helpers ──

def _find_openapi_spec() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent / "openapi.yaml",
        Path(__file__).resolve().parent.parent.parent.parent
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
    from .. import webapp as _wa
    project_root = Path(__file__).resolve().parent.parent.parent.parent
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


def get_events(h: object, parsed: object) -> None:
    from ..webapp import _sse_subscribe, _sse_unsubscribe, API_SCHEMA_VERSION
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
    from ..api import load_action_log
    h._send_json({"items": load_action_log(limit=limit)})
