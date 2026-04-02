"""Shared test infrastructure.

Provides HTTP helpers, server lifecycle mixin, and path setup
so individual test files don't duplicate boilerplate.
"""

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
from typing import Any
import unittest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


# ── HTTP helpers ──


def request_json(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 5,
) -> tuple[int, Any, dict[str, str]]:
    """Make an HTTP request and return (status_code, body, headers).

    Body is parsed as JSON if Content-Type is json, otherwise returned as str.
    On HTTP errors, the error body is parsed and returned with the error code.
    """
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                return resp.status, json.loads(body), dict(resp.headers)
            return (
                resp.status,
                body.decode("utf-8", errors="replace"),
                dict(resp.headers),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body), dict(exc.headers)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return (
                exc.code,
                body.decode("utf-8", errors="replace"),
                dict(exc.headers),
            )


def raw_request(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 5,
) -> tuple[int, bytes, dict[str, str]]:
    """Make a raw HTTP request and return (status_code, raw_body, headers)."""
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


# ── Server lifecycle ──


class APIServerTestCase(unittest.TestCase):
    """Base class that starts a fresh server per test class (fast).

    Usage:
        class MyTests(APIServerTestCase):
            def test_something(self):
                code, body, _ = request_json(f"{self.base}/api/status")
    """

    @classmethod
    def setUpClass(cls) -> None:
        from aria_queue.webapp import serve

        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = cls._tmp.name
        cls._server = serve(host="127.0.0.1", port=0)
        cls.port = cls._server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._server.server_close()
        cls._tmp.cleanup()


class APIServerPerTestCase(unittest.TestCase):
    """Base class that starts a fresh server per test method (isolated).

    Usage:
        class MyTests(APIServerPerTestCase):
            def test_something(self):
                code, body, _ = request_json(f"{self.base}/api/status")
    """

    def setUp(self) -> None:
        from aria_queue.webapp import serve

        self._tmp = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = self._tmp.name
        self._server = serve(host="127.0.0.1", port=0)
        self.port = self._server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.2)

    def tearDown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._tmp.cleanup()


class IsolatedTestCase(unittest.TestCase):
    """Base class with a fresh temp dir per test (isolated but no server)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()
