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

from . import __version__
from . import routes
from .api import (
    active_status,
    aria2_multicall,
    aria2_current_bandwidth,
    aria2_status,
    aria2_tell_active,
    aria2_tell_status,
    auto_preflight_on_run,  # noqa: F401 — re-exported for test patch compatibility
    is_macos,  # noqa: F401 — re-exported for test patch compatibility
    load_queue,
    load_state,
    preflight,  # noqa: F401 — re-exported for test patch compatibility
    start_background_process,  # noqa: F401 — re-exported for test patch compatibility
    summarize_queue,
)
from .core import cleanup_queue_state
from .storage import config_dir

import subprocess  # noqa: F401 — re-exported for test patch compatibility


STATUS_CACHE: dict[str, object] = {"ts": 0.0, "payload": None, "scope": None}
_STATUS_CACHE_LOCK = threading.Lock()
STATUS_CACHE_TTL = 2.0
API_SCHEMA_VERSION = "2"

# ── Request metrics ──
_metrics_lock = threading.Lock()
_metrics: dict[str, int] = {
    "requests_total": 0,
    "bytes_sent_total": 0,
    "bytes_received_total": 0,
    "errors_total": 0,
}
_start_monotonic = time.monotonic()
_started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")


def get_metrics() -> dict[str, object]:
    with _metrics_lock:
        snapshot: dict[str, object] = dict(_metrics)
    snapshot["uptime_seconds"] = round(time.monotonic() - _start_monotonic, 3)
    snapshot["started_at"] = _started_at
    with _sse_lock:
        snapshot["sse_clients"] = len(_sse_clients)
    return snapshot


# ── SSE event bus ──
_sse_clients: list[queue.Queue[str]] = []
_sse_lock = threading.Lock()


_TERMINAL_ITEM_STATUSES = {"complete", "error", "stopped", "cancelled"}


def _presented_status_name(status: str | None) -> str:
    value = str(status or "").strip().lower()
    if value in {"active", "waiting", "paused", "complete", "error"}:
        return value
    if value == "removed":
        return "stopped"
    return value or "queued"


def _overlay_aria2_transfer_fields(
    item: dict[str, object], info: dict[str, object]
) -> None:
    aria2_to_item = {
        "downloadSpeed": "download_speed",
        "completedLength": "completed_length",
        "totalLength": "total_length",
        "files": "files",
    }
    for aria2_key, item_key in aria2_to_item.items():
        if aria2_key in info:
            item[item_key] = info.get(aria2_key)


def _live_status_by_gid(
    items: list[dict[str, object]], port: int = 6800, timeout: int = 3
) -> dict[str, dict[str, object]]:
    gids: list[str] = []
    for item in items:
        if item.get("status") in _TERMINAL_ITEM_STATUSES:
            continue
        gid = str(item.get("gid") or "")
        if gid:
            gids.append(gid)
    if not gids:
        return {}

    results: dict[str, dict[str, object]] = {}
    fields = [
        "gid",
        "status",
        "errorCode",
        "errorMessage",
        "downloadSpeed",
        "completedLength",
        "totalLength",
        "files",
    ]
    try:
        calls = [
            {"methodName": "aria2.tellStatus", "params": [gid, fields]} for gid in gids
        ]
        batch_results = aria2_multicall(calls, port=port, timeout=timeout)
        for gid, result in zip(gids, batch_results):
            if isinstance(result, list) and result and isinstance(result[0], dict):
                results[gid] = result[0]
    except Exception:
        for gid in gids:
            try:
                results[gid] = aria2_tell_status(
                    gid, fields=fields, port=port, timeout=timeout
                )
            except Exception:
                continue
    return results


def _present_status_items(
    items: list[dict[str, object]], port: int = 6800, timeout: int = 3
) -> list[dict[str, object]]:
    live_by_gid = _live_status_by_gid(items, port=port, timeout=timeout)
    presented: list[dict[str, object]] = []
    for raw in items:
        item = dict(raw)
        memory_status = str(raw.get("status") or "")
        item["memory_status"] = memory_status
        item["status_source"] = "memory"
        gid = str(raw.get("gid") or "")
        info = live_by_gid.get(gid)
        if info:
            live_status = _presented_status_name(str(info.get("status") or ""))
            item["status"] = live_status
            item["live_status"] = live_status
            item["status_source"] = "aria2"
            item["error_code"] = info.get("errorCode")
            item["error_message"] = info.get("errorMessage")
            _overlay_aria2_transfer_fields(item, info)
        presented.append(item)
    return presented


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


def _status_cache_scope() -> str:
    return str(config_dir())


class AriaFlowHandler(BaseHTTPRequestHandler):
    _GET_ROUTES = {
        "/api/health": routes.get_health,
        "/api/openapi.yaml": routes.get_openapi_yaml,
        "/api/docs": routes.get_docs,
        "/api/tests": routes.get_tests,
        "/api": routes.get_api,
        "/api/scheduler": routes.get_scheduler,
        "/api/events": routes.get_events,
        "/api/bandwidth": routes.get_bandwidth,
        "/api/status": routes.get_status,
        "/api/log": routes.get_log,
        "/api/torrents": routes.get_torrents,
        "/api/peers": routes.get_peers,
        "/api/declaration": routes.get_declaration,
        "/api/aria2/get_global_option": routes.get_aria2_global_option,
        "/api/aria2/get_option": routes.get_aria2_option,
        "/api/aria2/option_tiers": routes.get_aria2_option_tiers,
        "/api/lifecycle": routes.get_lifecycle,
        "/api/downloads/archive": routes.get_archive,
        "/api/sessions": routes.get_sessions,
        "/api/sessions/stats": routes.get_session_stats,
    }

    _POST_ROUTES = {
        "/api/bandwidth/probe": routes.post_bandwidth_probe,
        "/api/downloads/add": routes.post_add,
        "/api/downloads/cleanup": routes.post_cleanup,
        "/api/scheduler/pause": routes.post_pause,
        "/api/scheduler/resume": routes.post_resume,
        "/api/scheduler/preflight": routes.post_preflight,
        "/api/scheduler/ucc": routes.post_ucc,
        "/api/declaration": routes.post_declaration,
        "/api/sessions/new": routes.post_session,
        "/api/aria2/change_global_option": routes.post_aria2_change_global_option,
        "/api/aria2/change_option": routes.post_aria2_change_option,
        "/api/aria2/set_limits": routes.post_aria2_set_limits,
    }

    def _invalidate_status_cache(self, event: str = "state_changed") -> None:
        scope = _status_cache_scope()
        with _STATUS_CACHE_LOCK:
            STATUS_CACHE["ts"] = 0.0
            STATUS_CACHE["payload"] = None
            STATUS_CACHE["scope"] = scope
        try:
            state = load_state()
            items = _present_status_items(load_queue())
            from .queue_ops import allowed_actions

            for item in items:
                item["allowed_actions"] = allowed_actions(item.get("status", ""))
            sse_data = {
                "_rev": state.get("_rev", 0),
                "server_version": __version__,
                "items": items,
                "state": state,
                "summary": summarize_queue(items),
            }
        except Exception:
            sse_data = {"_rev": 0, "server_version": __version__}
        _sse_publish(event, sse_data)

    def _status_payload(self, force: bool = False) -> dict:
        now = time.time()
        scope = _status_cache_scope()
        with _STATUS_CACHE_LOCK:
            cached = STATUS_CACHE.get("payload")
            ts = float(STATUS_CACHE.get("ts", 0.0))
            cached_scope = STATUS_CACHE.get("scope")
        if (
            not force
            and cached is not None
            and cached_scope == scope
            and now - ts < STATUS_CACHE_TTL
        ):
            return cached  # type: ignore[return-value]

        try:
            cleanup_queue_state()
        except Exception:
            pass

        from .queue_ops import allowed_actions

        state = load_state()
        items = _present_status_items(load_queue())
        for item in items:
            item["allowed_actions"] = allowed_actions(item.get("status", ""))
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
        # BG-8: include health fields so frontend can drop /api/health polling
        from .scheduler import check_disk_space

        disk_ok, disk_percent = check_disk_space()
        payload["health"] = {
            "disk_usage_percent": disk_percent,
            "disk_ok": disk_ok,
            **get_metrics(),
        }
        with _STATUS_CACHE_LOCK:
            STATUS_CACHE["ts"] = now
            STATUS_CACHE["payload"] = payload
            STATUS_CACHE["scope"] = scope
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
        with _metrics_lock:
            _metrics["bytes_sent_total"] += len(body)
            if status >= 400:
                _metrics["errors_total"] += 1

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
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
        with _metrics_lock:
            _metrics["requests_total"] += 1
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
                routes._error_payload(
                    "ui_not_served",
                    "ariaflow is API-only; use ariaflow-web for the dashboard",
                ),
                status=400,
            )
            return
        # Parameterized route: /api/downloads/{id}/files
        if (
            path.startswith("/api/downloads/")
            and path.endswith("/files")
            and path.count("/") == 4
        ):
            routes.get_item_files(self, parsed)
            return
        # Parameterized route: /api/torrents/{infohash}.torrent
        if path.startswith("/api/torrents/") and path.endswith(".torrent"):
            routes.get_torrent_file(self, parsed)
            return
        # Dispatch table
        handler = self._GET_ROUTES.get(path)
        if handler:
            handler(self, parsed)
        else:
            self._send_json(
                routes._error_payload("not_found", "resource not found"), status=404
            )

    def do_POST(self) -> None:  # noqa: N802
        with _metrics_lock:
            _metrics["requests_total"] += 1
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        with _metrics_lock:
            _metrics["bytes_received_total"] += length
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send_json(
                routes._error_payload(
                    "invalid_json", "request body must be valid JSON"
                ),
                status=400,
            )
            return

        # Parameterized route: /api/downloads/{id}/files (POST)
        if (
            path.startswith("/api/downloads/")
            and path.endswith("/files")
            and path.count("/") == 4
        ):
            routes.post_item_files(self, payload, path)
            return

        # Parameterized route: /api/lifecycle/{target}/{action}
        if path.startswith("/api/lifecycle/") and path.count("/") == 4:
            parts = path.split("/")
            target = parts[3]
            action = parts[4]
            routes.post_lifecycle_action(
                self, {"target": target, "action": action}, path
            )
            return

        # Parameterized route: /api/torrents/{infohash}/stop
        if path.startswith("/api/torrents/") and path.endswith("/stop"):
            infohash = path.split("/")[3]
            routes.post_torrent_stop(self, {"infohash": infohash}, path)
            return

        # Parameterized route: /api/downloads/{id}/{action}
        if path.startswith("/api/downloads/") and path.count("/") == 4:
            routes.post_item_action(self, payload, path)
            return

        # Dispatch table
        handler = self._POST_ROUTES.get(path)
        if handler:
            handler(self, payload, path)
        else:
            self._send_json(
                routes._error_payload("not_found", "resource not found"), status=404
            )

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self._send_json(
                routes._error_payload(
                    "invalid_json", "request body must be valid JSON"
                ),
                status=400,
            )
            return

        if path == "/api/declaration/preferences":
            routes.patch_declaration_preferences(self, payload)
            return

        self._send_json(
            routes._error_payload("not_found", "resource not found"), status=404
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), AriaFlowHandler)
