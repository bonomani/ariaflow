from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
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
                self.assertIn("ariaflow", page)
                bandwidth_page = urllib.request.urlopen(f"{base}/bandwidth", timeout=5).read().decode("utf-8")
                self.assertIn("Bandwidth", bandwidth_page)
                lifecycle_page = urllib.request.urlopen(f"{base}/lifecycle", timeout=5).read().decode("utf-8")
                self.assertIn("Service Status", lifecycle_page)
                options_page = urllib.request.urlopen(f"{base}/options", timeout=5).read().decode("utf-8")
                self.assertIn("Options", options_page)
                log_page = urllib.request.urlopen(f"{base}/log", timeout=5).read().decode("utf-8")
                self.assertIn("Log", log_page)
                self.assertIn("action-filter", log_page)
                self.assertIn("target-filter", log_page)
                self.assertIn("session-filter", log_page)
                status = request_json(f"{base}/api/status")
                self.assertIn("items", status)
                self.assertIn("state", status)
                self.assertIn("summary", status)
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
                    payload={"url": "https://example.com/file.gguf"},
                )
                self.assertEqual(added["added"]["url"], "https://example.com/file.gguf")
                added_many = request_json(
                    f"{base}/api/add",
                    method="POST",
                    payload={"url": "https://example.com/one.gguf\nhttps://example.com/two.gguf"},
                )
                self.assertIsInstance(added_many["added"], list)
                self.assertEqual(len(added_many["added"]), 2)
                paused = request_json(f"{base}/api/pause", method="POST")
                self.assertIn("paused", paused)
                resumed = request_json(f"{base}/api/resume", method="POST")
                self.assertIn("resumed", resumed)
                run = request_json(f"{base}/api/run", method="POST")
                self.assertTrue(run["started"])
            finally:
                server.shutdown()
                server.server_close()
