from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aria_queue.webapp import serve  # noqa: E402


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None
    headers = {}
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
                page = urllib.request.urlopen(f"{base}/", timeout=5).read().decode("utf-8")
                self.assertIn("ariaflow API", page)
                self.assertIn("API-only", page)
                for route in ("/bandwidth", "/lifecycle", "/options", "/log"):
                    with self.assertRaises(urllib.error.HTTPError) as route_error:
                        urllib.request.urlopen(f"{base}{route}", timeout=5)
                    self.assertEqual(route_error.exception.code, 404)
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
                options = request_json(f"{base}/api/options")
                self.assertIn("uic", options)
                lifecycle = request_json(f"{base}/api/lifecycle")
                self.assertIn("ariaflow", lifecycle)
                self.assertIn("meta", lifecycle["ariaflow"])
                self.assertIn("session_id", lifecycle)
                session = request_json(
                    f"{base}/api/session",
                    method="POST",
                    payload={"action": "new"},
                )
                self.assertTrue(session["ok"])
                self.assertIn("session", session)
                with patch("aria_queue.webapp.is_macos", return_value=True), \
                     patch("aria_queue.webapp.homebrew_install_ariaflow", return_value=["brew tap bonomani/ariaflow", "brew install ariaflow"]), \
                     patch("aria_queue.webapp.homebrew_uninstall_ariaflow", return_value=["brew uninstall ariaflow"]), \
                     patch("aria_queue.webapp.install_aria2_launchd", return_value=["load aria2"]), \
                     patch("aria_queue.webapp.uninstall_aria2_launchd", return_value=["unload aria2"]):
                    lifecycle_action = request_json(
                        f"{base}/api/lifecycle/action",
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
                    f"{base}/api/add",
                    method="POST",
                    payload={"items": [{"url": "https://example.com/file.gguf", "output": "file.gguf", "post_action_rule": "pending"}]},
                )
                self.assertTrue(added["ok"])
                self.assertEqual(added["count"], 1)
                self.assertEqual(added["added"][0]["url"], "https://example.com/file.gguf")
                self.assertEqual(added["added"][0]["output"], "file.gguf")
                self.assertEqual(added["added"][0]["post_action_rule"], "pending")
                added_many = request_json(
                    f"{base}/api/add",
                    method="POST",
                    payload={"items": [{"url": "https://example.com/one.gguf"}, {"url": "https://example.com/two.gguf"}]},
                )
                self.assertTrue(added_many["ok"])
                self.assertEqual(len(added_many["added"]), 2)
                paused = request_json(f"{base}/api/pause", method="POST")
                self.assertIn("paused", paused)
                resumed = request_json(f"{base}/api/resume", method="POST")
                self.assertIn("resumed", resumed)
                run = request_json(
                    f"{base}/api/run",
                    method="POST",
                    payload={"action": "start", "auto_preflight_on_run": False},
                )
                self.assertTrue(run["ok"])
                self.assertEqual(run["action"], "start")
                self.assertTrue(run["result"]["started"])
            finally:
                server.shutdown()
                server.server_close()

    def test_status_payload_does_not_synthesize_active_from_paused_queue_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            paused_item = {
                "id": "item-1",
                "gid": "gid-1",
                "url": "https://example.com/file.gguf",
                "status": "paused",
                "live_status": "active",
                "created_at": "2026-03-27T10:00:00+0100",
            }
            state = {
                "running": False,
                "paused": True,
                "active_gid": None,
                "active_url": None,
                "session_id": "session-1",
            }
            summary = {"queued": 0, "done": 0, "error": 0, "paused": 1, "total": 1}
            with patch("aria_queue.webapp.load_queue", return_value=[paused_item]), \
                 patch("aria_queue.webapp.load_state", return_value=state), \
                 patch("aria_queue.webapp.summarize_queue", return_value=summary), \
                 patch("aria_queue.webapp.current_bandwidth", return_value={"limit": "0"}), \
                 patch("aria_queue.webapp.aria_status", return_value={"reachable": True, "version": "1.37.0", "error": None}), \
                 patch("aria_queue.webapp.active_status", return_value=None), \
                 patch("aria_queue.webapp.active_gids", return_value=[]):
                server = serve(host="127.0.0.1", port=0)
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                time.sleep(0.2)
                try:
                    status = request_json(f"http://127.0.0.1:{port}/api/status")
                    self.assertEqual(status["items"][0]["status"], "paused")
                    self.assertNotIn("active", status)
                    self.assertNotIn("actives", status)
                    self.assertNotIn("bandwidth_global", status)
                    self.assertNotIn("aria2_global_options", status)
                finally:
                    server.shutdown()
                    server.server_close()

    def test_run_start_honors_request_auto_preflight_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIA_QUEUE_DIR"] = tmp
            server = serve(host="127.0.0.1", port=0)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.2)
            try:
                base = f"http://127.0.0.1:{port}"
                preflight_result = {
                    "status": "fail",
                    "exit_code": 1,
                    "gates": [],
                    "preferences": [],
                    "policies": [],
                    "warnings": [],
                    "hard_failures": ["aria2_available"],
                }
                with patch("aria_queue.webapp.auto_preflight_on_run", return_value=False), \
                     patch("aria_queue.webapp.preflight", return_value=preflight_result), \
                     patch("aria_queue.webapp.start_background_process") as start_background_process:
                    with self.assertRaises(urllib.error.HTTPError) as run_error:
                        request_json(
                            f"{base}/api/run",
                            method="POST",
                            payload={"action": "start", "auto_preflight_on_run": True},
                        )
                self.assertEqual(run_error.exception.code, 409)
                body = json.loads(run_error.exception.read().decode("utf-8"))
                self.assertFalse(body["ok"])
                self.assertEqual(body["error"], "preflight_blocked")
                self.assertTrue(body["effective_auto_preflight_on_run"])
                start_background_process.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
