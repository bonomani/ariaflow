from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
import unittest
from unittest.mock import patch

import conftest  # noqa: F401 — ensures sys.path is set up

from aria_queue.core import save_queue, save_state
from aria_queue.webapp import serve


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    """Make a JSON request and return the parsed body. Raises on HTTP errors."""
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


class WebSmokeTests(unittest.TestCase):
    def test_local_web_server_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            server = serve(host="127.0.0.1", port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.2)
            try:
                base = f"http://127.0.0.1:{port}"
                page = (
                    urllib.request.urlopen(f"{base}/", timeout=5).read().decode("utf-8")
                )
                # / redirects to /api/docs (Swagger UI)
                self.assertIn("Ariaflow API", page)
                for route in ("/bandwidth", "/lifecycle", "/options", "/log"):
                    with self.assertRaises(urllib.error.HTTPError) as route_error:
                        urllib.request.urlopen(f"{base}{route}", timeout=5)
                    self.assertEqual(route_error.exception.code, 400)
                status = request_json(f"{base}/api/status")
                self.assertIn("items", status)
                self.assertIn("state", status)
                self.assertIn("summary", status)
                self.assertNotIn("bandwidth_global", status)
                self.assertNotIn("aria2_global_options", status)
                log_data = request_json(f"{base}/api/log")
                self.assertIn("items", log_data)
                declaration = request_json(f"{base}/api/declaration")
                self.assertIn("uic", declaration)
                options = request_json(f"{base}/api/declaration")
                self.assertIn("uic", options)
                lifecycle = request_json(f"{base}/api/lifecycle")
                self.assertIn("ariaflow", lifecycle)
                self.assertIn("meta", lifecycle["ariaflow"])
                self.assertIn("session_id", lifecycle)
                with (
                    patch("aria_queue.webapp.is_macos", return_value=True),
                    patch(
                        "aria_queue.routes.lifecycle.homebrew_install_ariaflow",
                        return_value=[
                            "brew tap bonomani/ariaflow",
                            "brew install ariaflow",
                        ],
                    ),
                    patch(
                        "aria_queue.routes.lifecycle.homebrew_uninstall_ariaflow",
                        return_value=["brew uninstall ariaflow"],
                    ),
                    patch(
                        "aria_queue.routes.lifecycle.install_aria2_launchd",
                        return_value=["load aria2"],
                    ),
                    patch(
                        "aria_queue.routes.lifecycle.uninstall_aria2_launchd",
                        return_value=["unload aria2"],
                    ),
                ):
                    lifecycle_action = request_json(
                        f"{base}/api/lifecycle/ariaflow/install",
                        method="POST",
                        payload={"target": "ariaflow", "action": "install"},
                    )
                self.assertTrue(lifecycle_action["ok"])
                self.assertIn("lifecycle", lifecycle_action)
                saved = request_json(
                    f"{base}/api/declaration",
                    method="POST",
                    payload=declaration,
                )
                self.assertTrue(saved["saved"])
                added = request_json(
                    f"{base}/api/downloads/add",
                    method="POST",
                    payload={
                        "items": [
                            {
                                "url": "https://example.com/file.gguf",
                                "output": "file.gguf",
                                "post_action_rule": "pending",
                            }
                        ]
                    },
                )
                self.assertTrue(added["ok"])
                self.assertEqual(added["count"], 1)
                self.assertEqual(
                    added["added"][0]["url"], "https://example.com/file.gguf"
                )
                self.assertEqual(added["added"][0]["output"], "file.gguf")
                self.assertEqual(added["added"][0]["post_action_rule"], "pending")
                added_many = request_json(
                    f"{base}/api/downloads/add",
                    method="POST",
                    payload={
                        "items": [
                            {"url": "https://example.com/one.gguf"},
                            {"url": "https://example.com/two.gguf"},
                        ]
                    },
                )
                self.assertTrue(added_many["ok"])
                self.assertEqual(len(added_many["added"]), 2)
                paused = request_json(f"{base}/api/scheduler/pause", method="POST")
                self.assertIn("paused", paused)
                resumed = request_json(f"{base}/api/scheduler/resume", method="POST")
                self.assertIn("resumed", resumed)
            finally:
                server.shutdown()
                server.server_close()

    def test_status_payload_does_not_synthesize_active_from_paused_queue_item(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            save_queue(
                [
                    {
                        "id": "older-error",
                        "url": "https://example.com/error.iso",
                        "status": "error",
                        "gid": "gid-error",
                        "error_message": "boom",
                        "created_at": "2026-03-27T09:00:00+0100",
                    },
                    {
                        "id": "newer-error",
                        "url": "https://example.com/error.iso",
                        "status": "error",
                        "gid": "gid-error",
                        "error_message": "boom",
                        "created_at": "2026-03-27T10:00:00+0100",
                    },
                    {
                        "id": "item-1",
                        "gid": "gid-1",
                        "url": "https://example.com/file.gguf",
                        "status": "paused",
                        "live_status": "active",
                        "created_at": "2026-03-27T10:00:00+0100",
                    },
                ]
            )
            save_state(
                {
                    "running": False,
                    "paused": True,
                    "active_gid": None,
                    "active_url": None,
                    "session_id": "session-1",
                }
            )
            with (
                patch(
                    "aria_queue.webapp.aria2_current_bandwidth",
                    return_value={"limit": "0"},
                ),
                patch(
                    "aria_queue.webapp.aria2_status",
                    return_value={
                        "reachable": True,
                        "version": "1.37.0",
                        "error": None,
                    },
                ),
                patch(
                    "aria_queue.webapp.aria2_multicall",
                    return_value=[
                        [
                            {
                                "gid": "gid-1",
                                "status": "paused",
                                "errorCode": None,
                                "errorMessage": None,
                                "downloadSpeed": "0",
                                "completedLength": "0",
                                "totalLength": "100",
                                "files": [],
                            }
                        ]
                    ],
                ),
                patch("aria_queue.webapp.active_status", return_value=None),
                patch("aria_queue.webapp.aria2_tell_active", return_value=[]),
            ):
                server = serve(host="127.0.0.1", port=0)
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                time.sleep(0.2)
                try:
                    status = request_json(f"http://127.0.0.1:{port}/api/status")
                    self.assertEqual(len(status["items"]), 2)
                    paused = next(
                        item for item in status["items"] if item["status"] == "paused"
                    )
                    self.assertEqual(paused["memory_status"], "paused")
                    self.assertEqual(paused["status_source"], "aria2")
                    self.assertEqual(paused["live_status"], "paused")
                    self.assertNotIn("active", status)
                    self.assertNotIn("actives", status)
                    self.assertNotIn("bandwidth_global", status)
                    self.assertNotIn("aria2_global_options", status)
                finally:
                    server.shutdown()
                    server.server_close()

    def test_status_payload_prefers_live_aria2_status_over_stored_queue_status(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            save_queue(
                [
                    {
                        "id": "item-1",
                        "gid": "gid-1",
                        "url": "https://example.com/file.gguf",
                        "status": "active",
                        "created_at": "2026-03-27T10:00:00+0100",
                    },
                ]
            )
            save_state(
                {
                    "running": True,
                    "paused": False,
                    "active_gid": "gid-1",
                    "active_url": "https://example.com/file.gguf",
                    "session_id": "session-1",
                }
            )
            with (
                patch(
                    "aria_queue.webapp.aria2_current_bandwidth",
                    return_value={"limit": "0"},
                ),
                patch(
                    "aria_queue.webapp.aria2_status",
                    return_value={
                        "reachable": True,
                        "version": "1.37.0",
                        "error": None,
                    },
                ),
                patch(
                    "aria_queue.webapp.aria2_multicall",
                    return_value=[
                        [
                            {
                                "gid": "gid-1",
                                "status": "paused",
                                "errorCode": None,
                                "errorMessage": None,
                                "downloadSpeed": "0",
                                "completedLength": "12",
                                "totalLength": "100",
                                "files": [],
                            }
                        ]
                    ],
                ),
                patch("aria_queue.webapp.active_status", return_value=None),
                patch("aria_queue.webapp.aria2_tell_active", return_value=[]),
            ):
                server = serve(host="127.0.0.1", port=0)
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                time.sleep(0.2)
                try:
                    status = request_json(f"http://127.0.0.1:{port}/api/status")
                    item = status["items"][0]
                    self.assertEqual(item["status"], "paused")
                    self.assertEqual(item["memory_status"], "active")
                    self.assertEqual(item["status_source"], "aria2")
                    self.assertEqual(item["allowed_actions"], ["resume", "remove"])
                    self.assertEqual(item["completed_length"], "12")
                    self.assertEqual(status["summary"]["paused"], 1)
                    self.assertEqual(status["summary"]["active"], 0)
                finally:
                    server.shutdown()
                    server.server_close()

    def test_api_per_item_lifecycle(self) -> None:
        """Integration test: add → pause → resume → retry → remove via HTTP."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            server = serve(host="127.0.0.1", port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.2)
            try:
                base = f"http://127.0.0.1:{port}"

                # Add an item
                added = request_json(
                    f"{base}/api/downloads/add",
                    method="POST",
                    payload={
                        "items": [{"url": "https://example.com/test.bin"}],
                    },
                )
                self.assertTrue(added["ok"])
                item_id = added["added"][0]["id"]
                self.assertEqual(added["added"][0]["status"], "queued")

                # Pause it
                paused = request_json(
                    f"{base}/api/downloads/{item_id}/pause", method="POST"
                )
                self.assertTrue(paused["ok"])
                self.assertEqual(paused["item"]["status"], "paused")

                # Resume it
                resumed = request_json(
                    f"{base}/api/downloads/{item_id}/resume", method="POST"
                )
                self.assertTrue(resumed["ok"])
                self.assertEqual(resumed["item"]["status"], "queued")

                # Pause again, then verify double-pause is rejected
                request_json(f"{base}/api/downloads/{item_id}/pause", method="POST")
                try:
                    request_json(f"{base}/api/downloads/{item_id}/pause", method="POST")
                    self.fail("expected 400")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    body = json.loads(exc.read().decode("utf-8"))
                    self.assertEqual(body["error"], "invalid_state")

                # Resume, then manually set to error for retry test
                request_json(f"{base}/api/downloads/{item_id}/resume", method="POST")
                from aria_queue.core import load_queue, save_queue

                items = load_queue()
                items[0]["status"] = "error"
                items[0]["error_code"] = "1"
                save_queue(items)

                # Retry
                retried = request_json(
                    f"{base}/api/downloads/{item_id}/retry", method="POST"
                )
                self.assertTrue(retried["ok"])
                self.assertEqual(retried["item"]["status"], "queued")
                self.assertNotIn("error_code", retried["item"])

                # Remove
                removed = request_json(
                    f"{base}/api/downloads/{item_id}/remove", method="POST"
                )
                self.assertTrue(removed["ok"])
                self.assertTrue(removed["removed"])

                # Verify queue is empty
                status = request_json(f"{base}/api/status")
                self.assertEqual(len(status["items"]), 0)

                # Not found
                try:
                    request_json(
                        f"{base}/api/downloads/00000000-0000-0000-0000-000000000000/pause",
                        method="POST",
                    )
                    self.fail("expected 404")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 404)

                # Invalid action
                try:
                    request_json(
                        f"{base}/api/downloads/{item_id}/explode", method="POST"
                    )
                    self.fail("expected 400")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    body = json.loads(exc.read().decode("utf-8"))
                    self.assertEqual(body["error"], "invalid_action")

            finally:
                server.shutdown()
                server.server_close()

    def test_api_aria2_options_rejects_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            server = serve(host="127.0.0.1", port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.2)
            try:
                base = f"http://127.0.0.1:{port}"
                try:
                    request_json(
                        f"{base}/api/aria2/change_global_option",
                        method="POST",
                        payload={"dir": "/tmp/evil"},
                    )
                    self.fail("expected 400")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    body = json.loads(exc.read().decode("utf-8"))
                    self.assertEqual(body["error"], "rejected_options")
            finally:
                server.shutdown()
                server.server_close()

    def test_api_openapi_and_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            server = serve(host="127.0.0.1", port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.2)
            try:
                base = f"http://127.0.0.1:{port}"

                # OpenAPI spec
                with urllib.request.urlopen(
                    f"{base}/api/openapi.yaml", timeout=5
                ) as resp:
                    self.assertEqual(resp.status, 200)
                    content_type = resp.headers.get("Content-Type", "")
                    self.assertIn("yaml", content_type)
                    body = resp.read().decode("utf-8")
                    self.assertIn("openapi:", body)
                    self.assertIn("/api/status", body)

                # Swagger UI
                with urllib.request.urlopen(f"{base}/api/docs", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    html = resp.read().decode("utf-8")
                    self.assertIn("swagger-ui", html)
                    self.assertIn("openapi.yaml", html)

                # CORS headers
                with urllib.request.urlopen(f"{base}/api/status", timeout=5) as resp:
                    cors = resp.headers.get("Access-Control-Allow-Origin", "")
                    self.assertEqual(cors, "*")

            finally:
                server.shutdown()
                server.server_close()

    def test_api_tests_endpoint(self) -> None:
        """Test the /api/tests endpoint by mocking subprocess to avoid recursion."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            server = serve(host="127.0.0.1", port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.2)
            try:
                fake_output = "test_example (test_tic.TicAriaFlowTests) ... ok\n\n----------------------------------------------------------------------\nRan 1 test in 0.001s\n\nOK\n"
                fake_result = type(
                    "R", (), {"returncode": 0, "stderr": fake_output, "stdout": ""}
                )()
                with patch(
                    "aria_queue.webapp.subprocess.run", return_value=fake_result
                ):
                    result = request_json(f"http://127.0.0.1:{port}/api/tests")
                self.assertTrue(result["ok"])
                self.assertEqual(result["total"], 1)
                self.assertEqual(result["passed"], 1)
                self.assertEqual(result["failed"], 0)
                self.assertEqual(result["tests"][0]["status"], "ok")
            finally:
                server.shutdown()
                server.server_close()

    # test_run_start_honors_request_auto_preflight_override removed —
    # scheduler auto-starts, no start endpoint
