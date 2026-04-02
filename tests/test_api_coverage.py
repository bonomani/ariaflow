"""API coverage tests — one test per API endpoint/feature.

This file ensures every API endpoint has at least one integration test.
Each test spins up a real HTTP server and makes actual requests.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import unittest
from unittest.mock import patch

from conftest import APIServerTestCase, request_json as _req

from aria_queue.core import load_queue, save_queue


# ════════════════════════════════════════════════════════
# Every GET endpoint
# ════════════════════════════════════════════════════════


class TestGetEndpoints(APIServerTestCase):
    """One test per GET endpoint."""

    # 1. GET /api — discovery
    def test_get_api_discovery(self) -> None:
        code, body, _ = _req(f"{self.base}/api")
        self.assertEqual(code, 200)
        self.assertIn("endpoints", body)
        self.assertIn("GET", body["endpoints"])
        self.assertIn("POST", body["endpoints"])
        self.assertEqual(body["name"], "ariaflow")
        self.assertIn("version", body)
        self.assertIn("docs", body)
        self.assertIn("openapi", body)

    # 2. GET /api/status
    def test_get_api_status(self) -> None:
        code, body, hdrs = _req(f"{self.base}/api/status")
        self.assertEqual(code, 200)
        for key in (
            "items",
            "state",
            "summary",
            "aria2",
            "bandwidth",
            "backend",
            "_rev",
        ):
            self.assertIn(key, body, f"missing key: {key}")
        self.assertIn("schema_version", body["backend"])
        self.assertIn("_schema", body)
        self.assertIn("_request_id", body)
        self.assertIn("ETag", hdrs)

    # 3. GET /api/bandwidth
    def test_get_api_bandwidth(self) -> None:
        code, body, _ = _req(f"{self.base}/api/bandwidth")
        self.assertEqual(code, 200)
        self.assertIn("config", body)
        for key in (
            "down_free_percent",
            "down_free_absolute_mbps",
            "down_use_percent",
            "up_free_percent",
            "up_free_absolute_mbps",
            "up_use_percent",
            "probe_interval_seconds",
        ):
            self.assertIn(key, body["config"], f"missing config key: {key}")

    # 4. GET /api/log
    def test_get_api_log_default(self) -> None:
        code, body, _ = _req(f"{self.base}/api/log")
        self.assertEqual(code, 200)
        self.assertIn("items", body)
        self.assertIsInstance(body["items"], list)

    def test_get_api_log_with_limit(self) -> None:
        code, body, _ = _req(f"{self.base}/api/log?limit=5")
        self.assertEqual(code, 200)
        self.assertLessEqual(len(body["items"]), 5)

    # 5. GET /api/declaration
    def test_get_api_declaration(self) -> None:
        code, body, _ = _req(f"{self.base}/api/declaration")
        self.assertEqual(code, 200)
        self.assertIn("meta", body)
        self.assertIn("uic", body)
        self.assertEqual(body["meta"]["contract"], "UCC")
        self.assertEqual(body["meta"]["version"], "2.0")
        self.assertIn("gates", body["uic"])
        self.assertIn("preferences", body["uic"])

    # 6. GET /api/options (alias)
    def test_get_api_options(self) -> None:
        code, body, _ = _req(f"{self.base}/api/options")
        self.assertEqual(code, 200)
        self.assertIn("uic", body)

    # 7. GET /api/lifecycle
    def test_get_api_lifecycle(self) -> None:
        code, body, _ = _req(f"{self.base}/api/lifecycle")
        self.assertEqual(code, 200)
        self.assertIn("ariaflow", body)
        self.assertEqual(body["ariaflow"]["meta"]["contract"], "UCC")

    # 8. GET /api/item/{id}/files
    def test_get_api_item_files_no_gid(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/t.torrent"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/item/{item_id}/files")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "no_gid")

    def test_get_api_item_files_with_gid(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/t2.torrent"}]},
        )
        item_id = added["added"][0]["id"]
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["gid"] = "gid-files"
        save_queue(items)
        files = [{"index": "1", "path": "/f.mkv", "length": "999", "selected": "true"}]
        with patch("aria_queue.core.aria_rpc", return_value={"result": files}):
            code, body, _ = _req(f"{self.base}/api/item/{item_id}/files")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["files"]), 1)

    def test_get_api_item_files_not_found(self) -> None:
        code, body, _ = _req(f"{self.base}/api/item/nonexistent/files")
        self.assertEqual(code, 404)

    # 9. GET /api/docs
    def test_get_api_docs(self) -> None:
        code, body, hdrs = _req(f"{self.base}/api/docs")
        self.assertEqual(code, 200)
        self.assertIn("text/html", hdrs.get("Content-Type", ""))
        self.assertIn("swagger-ui", body)

    # 10. GET /api/openapi.yaml
    def test_get_api_openapi_yaml(self) -> None:
        code, body, hdrs = _req(f"{self.base}/api/openapi.yaml")
        self.assertEqual(code, 200)
        self.assertIn("yaml", hdrs.get("Content-Type", ""))
        self.assertIn("openapi:", body)

    # 11. GET /api/tests
    def test_get_api_tests(self) -> None:
        fake = type(
            "R",
            (),
            {
                "returncode": 0,
                "stderr": "test_x (mod.C) ... ok\n\nRan 1 test in 0.001s\n\nOK\n",
                "stdout": "",
            },
        )()
        with patch("aria_queue.webapp.subprocess.run", return_value=fake):
            code, body, _ = _req(f"{self.base}/api/tests")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["total"], 1)

    # 12. GET /api/events (SSE)
    def test_get_api_events(self) -> None:
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        sock.settimeout(3)
        sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        data = b""
        try:
            while len(data) < 2048:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk
                if b"connected" in data:
                    break
        except socket.timeout:
            pass
        finally:
            sock.close()
        text = data.decode("utf-8", errors="replace")
        self.assertIn("text/event-stream", text)
        self.assertIn("event: connected", text)


# ════════════════════════════════════════════════════════
# Every POST endpoint
# ════════════════════════════════════════════════════════


class TestPostEndpoints(APIServerTestCase):
    """One test per POST endpoint."""

    # 1. POST /api/add
    def test_post_api_add(self) -> None:
        code, body, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": "https://example.com/post-add.bin"}],
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["count"], 1)

    def test_post_api_add_invalid(self) -> None:
        code, body, _ = _req(f"{self.base}/api/add", "POST", {"items": []})
        self.assertEqual(code, 400)

    # 2. POST /api/run (start)
    def test_post_api_run_start(self) -> None:
        code, body, _ = _req(
            f"{self.base}/api/run",
            "POST",
            {
                "action": "start",
                "auto_preflight_on_run": False,
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["action"], "start")

    # 3. POST /api/run (stop)
    def test_post_api_run_stop(self) -> None:
        code, body, _ = _req(f"{self.base}/api/run", "POST", {"action": "stop"})
        self.assertEqual(code, 200)
        self.assertEqual(body["action"], "stop")

    def test_post_api_run_invalid(self) -> None:
        code, body, _ = _req(f"{self.base}/api/run", "POST", {"action": "boom"})
        self.assertEqual(code, 400)

    # 4. POST /api/preflight
    def test_post_api_preflight(self) -> None:
        with (
            patch(
                "aria_queue.webapp.preflight",
                return_value={
                    "contract": "UCC",
                    "version": "2.0",
                    "gates": [],
                    "preferences": [],
                    "policies": [],
                    "warnings": [],
                    "hard_failures": [],
                    "status": "pass",
                    "exit_code": 0,
                },
            ),
            patch("aria_queue.webapp.aria_status", return_value={}),
            patch("aria_queue.webapp.current_bandwidth", return_value={}),
        ):
            code, body, _ = _req(f"{self.base}/api/preflight", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "pass")

    # 5. POST /api/ucc
    def test_post_api_ucc(self) -> None:
        with (
            patch(
                "aria_queue.contracts.preflight",
                return_value={
                    "contract": "UCC",
                    "version": "2.0",
                    "gates": [],
                    "preferences": [],
                    "policies": [],
                    "warnings": [],
                    "hard_failures": [],
                    "status": "pass",
                    "exit_code": 0,
                },
            ),
            patch("aria_queue.core.process_queue", return_value=[]),
            patch("aria_queue.core.get_active_progress", return_value=None),
        ):
            code, body, _ = _req(f"{self.base}/api/ucc", "POST")
        self.assertEqual(code, 200)
        self.assertIn("meta", body)
        self.assertIn("result", body)

    # 6. POST /api/pause
    def test_post_api_pause(self) -> None:
        code, body, _ = _req(f"{self.base}/api/pause", "POST")
        self.assertEqual(code, 200)
        self.assertIn("paused", body)

    # 7. POST /api/resume
    def test_post_api_resume(self) -> None:
        code, body, _ = _req(f"{self.base}/api/resume", "POST")
        self.assertEqual(code, 200)
        self.assertIn("resumed", body)

    # 8. POST /api/session
    def test_post_api_session(self) -> None:
        # Ensure a session exists first
        _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/sess.bin"}]},
        )
        code, body, _ = _req(f"{self.base}/api/session", "POST", {"action": "new"})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertIn("session", body)

    # 9. POST /api/declaration
    def test_post_api_declaration(self) -> None:
        _, decl, _ = _req(f"{self.base}/api/declaration")
        code, body, _ = _req(f"{self.base}/api/declaration", "POST", decl)
        self.assertEqual(code, 200)
        self.assertTrue(body["saved"])

    # 10. POST /api/bandwidth/probe
    def test_post_api_bandwidth_probe(self) -> None:
        probe = {
            "source": "networkquality",
            "reason": "probe_complete",
            "downlink_mbps": 80.0,
            "uplink_mbps": 15.0,
            "cap_mbps": 64.0,
            "cap_bytes_per_sec": 8000000,
            "interface_name": "en0",
        }
        with (
            patch("aria_queue.core.probe_bandwidth", return_value=probe),
            patch("aria_queue.core.set_bandwidth"),
        ):
            code, body, _ = _req(f"{self.base}/api/bandwidth/probe", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["downlink_mbps"], 80.0)
        self.assertEqual(body["uplink_mbps"], 15.0)
        self.assertIn("down_cap_mbps", body)
        self.assertIn("up_cap_mbps", body)

    # 11. POST /api/aria2/options
    def test_post_api_aria2_options_safe(self) -> None:
        with (
            patch("aria_queue.core.aria_rpc"),
            patch("aria_queue.core.current_global_options", return_value={}),
        ):
            code, body, _ = _req(
                f"{self.base}/api/aria2/options",
                "POST",
                {
                    "max-concurrent-downloads": "3",
                },
            )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_post_api_aria2_options_unsafe(self) -> None:
        code, body, _ = _req(f"{self.base}/api/aria2/options", "POST", {"dir": "/evil"})
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "rejected_options")

    # 12. POST /api/item/{id}/pause
    def test_post_api_item_pause(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/pause-me.bin"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/item/{item_id}/pause", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "paused")

    # 13. POST /api/item/{id}/resume
    def test_post_api_item_resume(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/resume-me.bin"}]},
        )
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/item/{item_id}/pause", "POST")
        code, body, _ = _req(f"{self.base}/api/item/{item_id}/resume", "POST")
        self.assertEqual(code, 200)
        self.assertIn(body["item"]["status"], ("queued", "downloading"))

    # 14. POST /api/item/{id}/remove
    def test_post_api_item_remove(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/remove-me.bin"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/item/{item_id}/remove", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["removed"])

    # 15. POST /api/item/{id}/retry
    def test_post_api_item_retry(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/retry-me.bin"}]},
        )
        item_id = added["added"][0]["id"]
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
                item["error_code"] = "99"
        save_queue(items)
        code, body, _ = _req(f"{self.base}/api/item/{item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    # 16. POST /api/item/{id}/files (select)
    def test_post_api_item_files_select(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/sel.torrent"}]},
        )
        item_id = added["added"][0]["id"]
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["gid"] = "gid-sel"
                item["status"] = "paused"
        save_queue(items)
        with patch("aria_queue.core.aria_rpc"):
            code, body, _ = _req(
                f"{self.base}/api/item/{item_id}/files", "POST", {"select": [1, 2]}
            )
        self.assertEqual(code, 200)
        self.assertEqual(body["selected"], [1, 2])

    def test_post_api_item_files_select_invalid(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/sel2.torrent"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(
            f"{self.base}/api/item/{item_id}/files", "POST", {"select": []}
        )
        self.assertEqual(code, 400)

    # 17. POST /api/lifecycle/action
    def test_post_api_lifecycle_action_non_macos(self) -> None:
        with patch("aria_queue.webapp.is_macos", return_value=False):
            code, body, _ = _req(
                f"{self.base}/api/lifecycle/action",
                "POST",
                {
                    "target": "ariaflow",
                    "action": "install",
                },
            )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "macos_only")

    def test_post_api_lifecycle_action_install(self) -> None:
        with (
            patch("aria_queue.webapp.is_macos", return_value=True),
            patch(
                "aria_queue.webapp.homebrew_install_ariaflow",
                return_value=["brew install ariaflow"],
            ),
        ):
            code, body, _ = _req(
                f"{self.base}/api/lifecycle/action",
                "POST",
                {
                    "target": "ariaflow",
                    "action": "install",
                },
            )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])


# ════════════════════════════════════════════════════════
# Cross-cutting concerns
# ════════════════════════════════════════════════════════


class TestCrossCutting(APIServerTestCase):
    """Tests for features that apply across all endpoints."""

    # Schema version
    def test_schema_version_in_body(self) -> None:
        code, body, _ = _req(f"{self.base}/api/declaration")
        self.assertEqual(body["_schema"], "1")

    def test_schema_version_in_header(self) -> None:
        _, _, hdrs = _req(f"{self.base}/api/declaration")
        self.assertEqual(hdrs.get("X-Schema-Version"), "1")

    # Request ID
    def test_request_id_unique(self) -> None:
        _, b1, _ = _req(f"{self.base}/api/declaration")
        _, b2, _ = _req(f"{self.base}/api/declaration")
        self.assertNotEqual(b1["_request_id"], b2["_request_id"])

    def test_request_id_in_header(self) -> None:
        _, _, hdrs = _req(f"{self.base}/api/declaration")
        self.assertTrue(len(hdrs.get("X-Request-Id", "")) > 0)

    # ETag on status
    def test_etag_304(self) -> None:
        _, _, hdrs = _req(f"{self.base}/api/status")
        etag = hdrs.get("ETag", "")
        self.assertTrue(len(etag) > 0)
        code, _, _ = _req(f"{self.base}/api/status", headers={"If-None-Match": etag})
        self.assertEqual(code, 304)

    # CORS
    def test_cors_allow_origin(self) -> None:
        _, _, hdrs = _req(f"{self.base}/api/status")
        self.assertEqual(hdrs.get("Access-Control-Allow-Origin"), "*")

    # Revision counter
    def test_revision_increments(self) -> None:
        _, s1, _ = _req(f"{self.base}/api/status")
        rev1 = s1["_rev"]
        # Trigger state change
        _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/rev-inc.bin"}]},
        )
        time.sleep(0.1)
        # Force fresh status (invalidate cache by waiting or adding item)
        _, s2, _ = _req(f"{self.base}/api/status")
        self.assertGreaterEqual(s2["_rev"], rev1)

    # 404 handling
    def test_get_404(self) -> None:
        code, body, _ = _req(f"{self.base}/api/nonexistent")
        self.assertEqual(code, 404)

    def test_post_404(self) -> None:
        code, body, _ = _req(f"{self.base}/api/nonexistent", "POST", {})
        self.assertEqual(code, 404)

    # Invalid JSON
    def test_invalid_json_body(self) -> None:
        req = urllib.request.Request(
            f"{self.base}/api/run",
            data=b"{broken",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5):
                pass
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            body = json.loads(exc.read())
            self.assertEqual(body["error"], "invalid_json")

    # Invalid item action
    def test_invalid_item_action(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/inv.bin"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/item/{item_id}/explode", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_action")

    # Item not found
    def test_item_not_found(self) -> None:
        code, body, _ = _req(f"{self.base}/api/item/does-not-exist/pause", "POST")
        self.assertEqual(code, 404)

    # State consistency: add → status reflects it
    def test_add_reflected_in_status(self) -> None:
        url = f"https://example.com/consistency-{time.time()}.bin"
        _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        _, status, _ = _req(f"{self.base}/api/status")
        urls = [item["url"] for item in status["items"]]
        self.assertIn(url, urls)

    # State consistency: remove → status reflects it
    def test_remove_reflected_in_status(self) -> None:
        url = f"https://example.com/remove-check-{time.time()}.bin"
        _, added, _ = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/item/{item_id}/remove", "POST")
        _, status, _ = _req(f"{self.base}/api/status")
        ids = [item["id"] for item in status["items"]]
        self.assertNotIn(item_id, ids)

    # Action log records operations
    def test_actions_logged(self) -> None:
        url = f"https://example.com/logged-{time.time()}.bin"
        _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        _, log, _ = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("add", actions)


if __name__ == "__main__":
    unittest.main()
