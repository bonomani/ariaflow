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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aria_queue.web import serve  # noqa: E402


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
            server = serve(host="127.0.0.1", port=8765)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            time.sleep(0.2)
            try:
                page = urllib.request.urlopen("http://127.0.0.1:8765/", timeout=5).read().decode("utf-8")
                self.assertIn("ariaflow", page)
                status = request_json("http://127.0.0.1:8765/api/status")
                self.assertIn("items", status)
                self.assertIn("state", status)
                self.assertIn("summary", status)
                declaration = request_json("http://127.0.0.1:8765/api/declaration")
                self.assertIn("uic", declaration)
                lifecycle = request_json("http://127.0.0.1:8765/api/lifecycle")
                self.assertIn("ariaflow", lifecycle)
                self.assertIn("meta", lifecycle["ariaflow"])
                install_preview = request_json("http://127.0.0.1:8765/api/lifecycle/install", method="POST")
                self.assertIn("aria2-launchd", install_preview)
                self.assertNotIn("ariaflow-serve-launchd", install_preview)
                uninstall_preview = request_json("http://127.0.0.1:8765/api/lifecycle/uninstall", method="POST")
                self.assertIn("aria2-launchd", uninstall_preview)
                self.assertNotIn("ariaflow-serve-launchd", uninstall_preview)
                saved = request_json(
                    "http://127.0.0.1:8765/api/declaration",
                    method="POST",
                    payload=declaration,
                )
                self.assertTrue(saved["saved"])
                added = request_json(
                    "http://127.0.0.1:8765/api/add",
                    method="POST",
                    payload={"url": "https://example.com/file.gguf"},
                )
                self.assertEqual(added["added"]["url"], "https://example.com/file.gguf")
                paused = request_json("http://127.0.0.1:8765/api/pause", method="POST")
                self.assertTrue(paused["paused"])
                resumed = request_json("http://127.0.0.1:8765/api/resume", method="POST")
                self.assertFalse(resumed["paused"])
                run = request_json("http://127.0.0.1:8765/api/run", method="POST")
                self.assertTrue(run["started"])
            finally:
                server.shutdown()
                server.server_close()
