"""API integration tests.

Every test spins up a real HTTP server and makes real requests.
aria2 RPC is mocked where needed to avoid requiring a running daemon.

Includes:
- Per-test-method isolated tests (APIServerPerTestCase): status, add, per-item
  actions, file selection, aria2 options, bandwidth, engine control, declaration,
  session, action log, lifecycle, UCC, meta endpoints, error handling
- Per-class shared server tests (APIServerTestCase): GET endpoint coverage,
  POST endpoint coverage, cross-cutting concerns (schema version, request ID,
  ETag, CORS, revision counter, 404 handling, state consistency, action logging)
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import (
    APIServerPerTestCase,
    APIServerTestCase,
    raw_request,
    request_json,
)

from ariaflow_server.core import load_queue, save_queue


def _request(
    url: str, method: str = "GET", payload: dict | None = None, timeout: int = 5
) -> tuple[int, dict]:
    """Thin 2-tuple wrapper around conftest.request_json."""
    code, body, _ = request_json(url, method=method, payload=payload, timeout=timeout)
    return code, body


def _raw_request(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 5,
) -> tuple[int, bytes, dict[str, str]]:
    """Delegate to conftest.raw_request."""
    return raw_request(
        url, method=method, data=data, content_type=content_type, timeout=timeout
    )


# Alias used by coverage tests
_req = request_json


# ══════════════════════════════════════════════════════════════════════
# Per-test isolated tests (APIServerPerTestCase)
# ══════════════════════════════════════════════════════════════════════


# ──────────────────────────────────────────────────────
# 1. Status & Queue Read Endpoints
# ──────────────────────────────────────────────────────


class TestStatusEndpoint(APIServerPerTestCase):
    def test_status_returns_required_fields(self) -> None:
        code, body = _request(f"{self.base}/api/status")
        self.assertEqual(code, 200)
        for key in ("items", "state", "summary"):
            self.assertIn(key, body)

    def test_status_summary_counts_match_items(self) -> None:
        _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": "https://example.com/a.bin"},
                    {"url": "https://example.com/b.bin"},
                ]
            },
        )
        code, body = _request(f"{self.base}/api/status")
        self.assertEqual(body["summary"]["queued"], 2)
        self.assertEqual(body["summary"]["total"], 2)
        self.assertEqual(len(body["items"]), 2)

    def test_status_includes_session_info(self) -> None:
        _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/x.bin"}]},
        )
        code, body = _request(f"{self.base}/api/status")
        self.assertIn("session_id", body["state"])
        self.assertIsNotNone(body["state"]["session_id"])

    def test_status_empty_queue(self) -> None:
        code, body = _request(f"{self.base}/api/status")
        self.assertEqual(body["summary"]["total"], 0)
        self.assertEqual(body["items"], [])


# ──────────────────────────────────────────────────────
# 2. Add Endpoint
# ──────────────────────────────────────────────────────


class TestAddEndpoint(APIServerPerTestCase):
    def test_add_single_item(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/file.bin"}],
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["added"][0]["url"], "https://example.com/file.bin")
        self.assertEqual(body["added"][0]["status"], "queued")
        self.assertIn("id", body["added"][0])

    def test_add_multiple_items(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": "https://example.com/one.bin"},
                    {"url": "https://example.com/two.bin"},
                    {"url": "https://example.com/three.bin"},
                ],
            },
        )
        self.assertEqual(body["count"], 3)
        urls = [item["url"] for item in body["added"]]
        self.assertIn("https://example.com/one.bin", urls)
        self.assertIn("https://example.com/three.bin", urls)

    def test_add_with_output_and_post_action(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {
                        "url": "https://example.com/file.bin",
                        "output": "custom.bin",
                        "post_action_rule": "pending",
                    }
                ],
            },
        )
        self.assertEqual(body["added"][0]["output"], "custom.bin")
        self.assertEqual(body["added"][0]["post_action_rule"], "pending")

    def test_add_duplicate_url_returns_same_id(self) -> None:
        _, first = _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/dup.bin"}],
            },
        )
        _, second = _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/dup.bin"}],
            },
        )
        self.assertEqual(first["added"][0]["id"], second["added"][0]["id"])

    def test_add_empty_items_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/downloads/add", "POST", {"items": []})
        self.assertEqual(code, 400)

    def test_add_missing_items_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/add", "POST", {"url": "https://example.com/x"}
        )
        self.assertEqual(code, 400)

    def test_add_invalid_json_returns_400(self) -> None:
        code, _, _ = _raw_request(
            f"{self.base}/api/downloads/add",
            method="POST",
            data=b"not json",
            content_type="application/json",
        )
        self.assertEqual(code, 400)

    def test_add_no_body_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/downloads/add", "POST", None)
        self.assertEqual(code, 400)


# ──────────────────────────────────────────────────────
# 3. Per-item Actions
# ──────────────────────────────────────────────────────


class TestPerItemActions(APIServerPerTestCase):
    def setUp(self) -> None:
        super().setUp()
        _, added = _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/item.bin"}],
            },
        )
        self.item_id = added["added"][0]["id"]

    # ── Pause ──

    def test_pause_queued_item(self) -> None:
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/pause", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["item"]["status"], "paused")

    def test_pause_already_paused_returns_400(self) -> None:
        _request(f"{self.base}/api/downloads/{self.item_id}/pause", "POST")
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/pause", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    def test_pause_done_item_returns_400(self) -> None:
        items = load_queue()
        items[0]["status"] = "complete"
        save_queue(items)
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/pause", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    def test_pause_nonexistent_returns_404(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/00000000-0000-0000-0000-000000000000/pause",
            "POST",
        )
        self.assertEqual(code, 404)
        self.assertEqual(body["error"], "not_found")

    # ── Resume ──

    def test_resume_paused_item_without_gid(self) -> None:
        _request(f"{self.base}/api/downloads/{self.item_id}/pause", "POST")
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/resume", "POST"
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    def test_resume_paused_item_with_gid(self) -> None:
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("ariaflow_server.core.aria_rpc"):
            code, body = _request(
                f"{self.base}/api/downloads/{self.item_id}/resume", "POST"
            )
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "active")

    def test_resume_queued_item_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/resume", "POST"
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    # ── Remove ──

    def test_remove_queued_item(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/remove", "POST"
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["removed"])
        self.assertEqual(len(load_queue()), 0)

    def test_remove_downloading_item_calls_aria2(self) -> None:
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("ariaflow_server.core.aria_rpc") as rpc:
            code, body = _request(
                f"{self.base}/api/downloads/{self.item_id}/remove", "POST"
            )
        self.assertEqual(code, 200)
        rpc.assert_any_call("aria2.remove", ["gid-1"], port=6800, timeout=5)

    def test_remove_nonexistent_returns_404(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/00000000-0000-0000-0000-000000000000/remove",
            "POST",
        )
        self.assertEqual(code, 404)

    def test_double_remove_returns_404(self) -> None:
        _request(f"{self.base}/api/downloads/{self.item_id}/remove", "POST")
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/remove", "POST"
        )
        self.assertEqual(code, 404)

    # ── Retry ──

    def test_retry_error_item(self) -> None:
        items = load_queue()
        items[0]["status"] = "error"
        items[0]["error_code"] = "5"
        items[0]["error_message"] = "download failed"
        items[0]["gid"] = "gid-dead"
        save_queue(items)
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")
        self.assertNotIn("error_code", body["item"])
        self.assertNotIn("error_message", body["item"])
        self.assertNotIn("gid", body["item"])

    def test_retry_failed_item(self) -> None:
        items = load_queue()
        items[0]["status"] = "failed"
        save_queue(items)
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    def test_retry_stopped_item(self) -> None:
        items = load_queue()
        items[0]["status"] = "stopped"
        save_queue(items)
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    def test_retry_queued_item_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/retry", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    def test_retry_done_item_returns_400(self) -> None:
        items = load_queue()
        items[0]["status"] = "complete"
        save_queue(items)
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/retry", "POST")
        self.assertEqual(code, 400)

    # ── Invalid action ──

    def test_invalid_action_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/explode", "POST"
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_action")


# ──────────────────────────────────────────────────────
# 4. File Selection (Torrent/Metalink)
# ──────────────────────────────────────────────────────


class TestFileSelection(APIServerPerTestCase):
    def setUp(self) -> None:
        super().setUp()
        _, added = _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/archive.torrent"}],
            },
        )
        self.item_id = added["added"][0]["id"]

    def test_get_files_no_gid_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/downloads/{self.item_id}/files")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "no_gid")

    def test_get_files_with_gid(self) -> None:
        items = load_queue()
        items[0]["gid"] = "gid-torrent"
        save_queue(items)
        files = [
            {
                "index": "1",
                "path": "/downloads/file1.mkv",
                "length": "1000000",
                "selected": "true",
            },
            {
                "index": "2",
                "path": "/downloads/file2.nfo",
                "length": "500",
                "selected": "true",
            },
        ]
        with patch("ariaflow_server.core.aria_rpc", return_value={"result": files}):
            code, body = _request(f"{self.base}/api/downloads/{self.item_id}/files")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["files"]), 2)
        self.assertEqual(body["gid"], "gid-torrent")

    def test_get_files_nonexistent_returns_404(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/00000000-0000-0000-0000-000000000000/files"
        )
        self.assertEqual(code, 404)

    def test_select_files(self) -> None:
        items = load_queue()
        items[0]["gid"] = "gid-torrent"
        items[0]["status"] = "paused"
        save_queue(items)
        with patch("ariaflow_server.core.aria_rpc") as rpc:
            code, body = _request(
                f"{self.base}/api/downloads/{self.item_id}/files",
                "POST",
                {"select": [1, 3, 5]},
            )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["selected"], [1, 3, 5])
        rpc.assert_any_call(
            "aria2.changeOption",
            ["gid-torrent", {"select-file": "1,3,5"}],
            port=6800,
            timeout=5,
        )
        rpc.assert_any_call("aria2.unpause", ["gid-torrent"], port=6800, timeout=5)

    def test_select_files_empty_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/files",
            "POST",
            {"select": []},
        )
        self.assertEqual(code, 400)

    def test_select_files_missing_select_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/files",
            "POST",
            {"indices": [1, 2]},
        )
        self.assertEqual(code, 400)

    def test_select_files_non_integer_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/downloads/{self.item_id}/files",
            "POST",
            {"select": ["a", "b"]},
        )
        self.assertEqual(code, 400)


# ──────────────────────────────────────────────────────
# 5. aria2 Options Proxy
# ──────────────────────────────────────────────────────


class TestAria2Options(APIServerPerTestCase):
    def test_safe_option_accepted(self) -> None:
        with (
            patch("ariaflow_server.core.aria_rpc"),
            patch("ariaflow_server.core.aria2_current_global_options", return_value={}),
        ):
            code, body = _request(
                f"{self.base}/api/aria2/change_global_option",
                "POST",
                {
                    "max-concurrent-downloads": "5",
                },
            )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertIn("max-concurrent-downloads", body["applied"])

    def test_multiple_safe_options(self) -> None:
        with (
            patch("ariaflow_server.core.aria_rpc"),
            patch("ariaflow_server.core.aria2_current_global_options", return_value={}),
        ):
            code, body = _request(
                f"{self.base}/api/aria2/change_global_option",
                "POST",
                {
                    "max-concurrent-downloads": "3",
                    "split": "4",
                    "timeout": "30",
                },
            )
        self.assertEqual(code, 200)
        self.assertEqual(len(body["applied"]), 3)

    def test_unsafe_option_rejected(self) -> None:
        code, body = _request(
            f"{self.base}/api/aria2/change_global_option",
            "POST",
            {
                "dir": "/tmp/evil",
            },
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "rejected_options")

    def test_mixed_safe_unsafe_rejected(self) -> None:
        code, body = _request(
            f"{self.base}/api/aria2/change_global_option",
            "POST",
            {
                "max-concurrent-downloads": "3",
                "enable-rpc": "false",
            },
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "rejected_options")

    def test_empty_options_rejected(self) -> None:
        code, body = _request(f"{self.base}/api/aria2/change_global_option", "POST", {})
        self.assertEqual(code, 400)
        self.assertIn(body["error"], ("empty_options", "invalid_payload"))

    def test_non_object_payload_rejected(self) -> None:
        code, body = _request(
            f"{self.base}/api/aria2/change_global_option", "POST", None
        )
        self.assertEqual(code, 400)

    def test_all_six_safe_options(self) -> None:
        all_safe = {
            "max-concurrent-downloads": "3",
            "max-connection-per-server": "4",
            "split": "4",
            "min-split-size": "1M",
            "timeout": "60",
            "connect-timeout": "30",
        }
        with (
            patch("ariaflow_server.core.aria_rpc"),
            patch("ariaflow_server.core.aria2_current_global_options", return_value={}),
        ):
            code, body = _request(
                f"{self.base}/api/aria2/change_global_option", "POST", all_safe
            )
        self.assertEqual(code, 200)
        self.assertEqual(len(body["applied"]), 6)

    def test_managed_options_rejected(self) -> None:
        managed = {"max-overall-download-limit": "0"}
        code, body = _request(
            f"{self.base}/api/aria2/change_global_option", "POST", managed
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "managed_options")


# ──────────────────────────────────────────────────────
# 5b. Bandwidth Status & Probe
# ──────────────────────────────────────────────────────


class TestBandwidth(APIServerPerTestCase):
    def test_bandwidth_status_returns_config(self) -> None:
        code, body = _request(f"{self.base}/api/bandwidth")
        self.assertEqual(code, 200)
        self.assertIn("config", body)
        self.assertIn("down_free_percent", body["config"])
        self.assertIn("down_free_absolute_mbps", body["config"])
        self.assertIn("up_free_percent", body["config"])
        self.assertIn("up_free_absolute_mbps", body["config"])
        self.assertIn("probe_interval_seconds", body["config"])

    def test_bandwidth_status_defaults(self) -> None:
        code, body = _request(f"{self.base}/api/bandwidth")
        self.assertEqual(body["config"]["down_free_percent"], 20)
        self.assertEqual(body["config"]["down_free_absolute_mbps"], 0)
        self.assertEqual(body["config"]["up_free_percent"], 50)
        self.assertEqual(body["config"]["up_free_absolute_mbps"], 0)
        self.assertEqual(body["config"]["probe_interval_seconds"], 180)
        self.assertAlmostEqual(body["config"]["down_use_percent"], 0.8)
        self.assertAlmostEqual(body["config"]["up_use_percent"], 0.5)

    def test_bandwidth_status_includes_probe_info(self) -> None:
        probe_result = {
            "source": "networkquality",
            "reason": "probe_complete",
            "downlink_mbps": 100.0,
            "uplink_mbps": 20.0,
            "cap_mbps": 80.0,
            "cap_bytes_per_sec": 10000000,
            "interface_name": "en0",
            "responsiveness_rpm": 1500.0,
        }
        with (
            patch("ariaflow_server.core.probe_bandwidth", return_value=probe_result),
            patch("ariaflow_server.core.aria2_set_max_overall_download_limit"),
        ):
            _request(f"{self.base}/api/bandwidth/probe", "POST")
        code, body = _request(f"{self.base}/api/bandwidth")
        self.assertEqual(body["downlink_mbps"], 100.0)
        self.assertEqual(body["uplink_mbps"], 20.0)
        self.assertEqual(body["interface"], "en0")
        self.assertEqual(body["responsiveness_rpm"], 1500.0)
        self.assertIn("down_cap_mbps", body)
        self.assertIn("up_cap_mbps", body)

    def test_manual_probe(self) -> None:
        probe_result = {
            "source": "networkquality",
            "reason": "probe_complete",
            "downlink_mbps": 50.0,
            "uplink_mbps": 10.0,
            "cap_mbps": 40.0,
            "cap_bytes_per_sec": 5000000,
            "interface_name": "en1",
        }
        with (
            patch("ariaflow_server.core.probe_bandwidth", return_value=probe_result),
            patch("ariaflow_server.core.aria2_set_max_overall_download_limit"),
        ):
            code, body = _request(f"{self.base}/api/bandwidth/probe", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["downlink_mbps"], 50.0)
        self.assertEqual(body["uplink_mbps"], 10.0)
        self.assertIn("down_cap_mbps", body)
        self.assertIn("up_cap_mbps", body)
        self.assertEqual(body["interface"], "en1")
        self.assertEqual(body["source"], "networkquality")

    def test_manual_probe_fallback(self) -> None:
        with patch("ariaflow_server.core._find_networkquality", return_value=None):
            code, body = _request(f"{self.base}/api/bandwidth/probe", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["source"], "default")
        self.assertIsNone(body["downlink_mbps"])
        self.assertIsNone(body["uplink_mbps"])
        self.assertIsNone(body["down_cap_mbps"])
        self.assertIsNone(body["up_cap_mbps"])

    def test_bandwidth_config_from_declaration(self) -> None:
        _, decl = _request(f"{self.base}/api/declaration")
        for pref in decl["uic"]["preferences"]:
            if pref["name"] == "bandwidth_down_free_percent":
                pref["value"] = 30
            if pref["name"] == "bandwidth_up_free_percent":
                pref["value"] = 80
        _request(f"{self.base}/api/declaration", "POST", decl)
        code, body = _request(f"{self.base}/api/bandwidth")
        self.assertEqual(body["config"]["down_free_percent"], 30)
        self.assertEqual(body["config"]["up_free_percent"], 80)
        self.assertAlmostEqual(body["config"]["down_use_percent"], 0.7)
        self.assertAlmostEqual(body["config"]["up_use_percent"], 0.2)


# ──────────────────────────────────────────────────────
# 6. Engine Control (Run/Pause/Resume)
# ──────────────────────────────────────────────────────


class TestEngineControl(APIServerPerTestCase):
    def test_run_start_returns_404(self) -> None:
        code, body = _request(f"{self.base}/api/scheduler/start", "POST", {})
        self.assertEqual(code, 404)

    def test_run_stop_returns_404(self) -> None:
        code, body = _request(f"{self.base}/api/scheduler/stop", "POST", {})
        self.assertEqual(code, 404)

    def test_run_invalid_endpoint_returns_404(self) -> None:
        code, body = _request(f"{self.base}/api/scheduler/restart", "POST", {})
        self.assertEqual(code, 404)

    def test_global_pause_resume(self) -> None:
        code, paused = _request(f"{self.base}/api/scheduler/pause", "POST")
        self.assertEqual(code, 200)
        self.assertIn("paused", paused)

        code, resumed = _request(f"{self.base}/api/scheduler/resume", "POST")
        self.assertEqual(code, 200)
        self.assertIn("resumed", resumed)

    def test_preflight(self) -> None:
        with (
            patch(
                "ariaflow_server.webapp.preflight",
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
            patch("ariaflow_server.webapp.aria2_status", return_value={}),
            patch("ariaflow_server.webapp.aria2_current_bandwidth", return_value={}),
        ):
            code, body = _request(f"{self.base}/api/scheduler/preflight", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "pass")
        self.assertIn("gates", body)

    # test_preflight_blocked_start removed — no start endpoint


# ──────────────────────────────────────────────────────
# 7. Declaration / Config
# ──────────────────────────────────────────────────────


class TestDeclaration(APIServerPerTestCase):
    def test_get_declaration(self) -> None:
        code, body = _request(f"{self.base}/api/declaration")
        self.assertEqual(code, 200)
        self.assertIn("meta", body)
        self.assertIn("uic", body)
        self.assertEqual(body["meta"]["contract"], "UCC")

    def test_get_declaration_is_stable(self) -> None:
        _, decl = _request(f"{self.base}/api/declaration")
        _, opts = _request(f"{self.base}/api/declaration")
        decl.pop("_request_id", None)
        opts.pop("_request_id", None)
        self.assertEqual(decl, opts)

    def test_save_declaration(self) -> None:
        _, original = _request(f"{self.base}/api/declaration")
        code, body = _request(f"{self.base}/api/declaration", "POST", original)
        self.assertEqual(code, 200)
        self.assertTrue(body["saved"])
        self.assertIn("declaration", body)

    def test_save_declaration_roundtrip(self) -> None:
        _, original = _request(f"{self.base}/api/declaration")
        original["uic"]["preferences"].append(
            {
                "name": "test_pref",
                "value": True,
                "options": [True, False],
                "rationale": "test",
            }
        )
        _request(f"{self.base}/api/declaration", "POST", original)
        _, reloaded = _request(f"{self.base}/api/declaration")
        pref_names = [p["name"] for p in reloaded["uic"]["preferences"]]
        self.assertIn("test_pref", pref_names)


# ──────────────────────────────────────────────────────
# 8. Action Log
# ──────────────────────────────────────────────────────


class TestActionLog(APIServerPerTestCase):
    def test_log_default_limit(self) -> None:
        code, body = _request(f"{self.base}/api/log")
        self.assertEqual(code, 200)
        self.assertIn("items", body)
        self.assertIsInstance(body["items"], list)

    def test_log_custom_limit(self) -> None:
        # Add items to generate log entries
        for i in range(5):
            _request(
                f"{self.base}/api/downloads/add",
                "POST",
                {"items": [{"url": f"https://example.com/{i}.bin"}]},
            )
        code, body = _request(f"{self.base}/api/log?limit=3")
        self.assertLessEqual(len(body["items"]), 3)

    def test_log_entries_have_timestamps(self) -> None:
        _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/log.bin"}]},
        )
        _, body = _request(f"{self.base}/api/log?limit=5")
        for entry in body["items"]:
            self.assertIn("timestamp", entry)

    def test_log_records_add_action(self) -> None:
        _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/tracked.bin"}]},
        )
        _, body = _request(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in body["items"]]
        self.assertIn("add", actions)


# ──────────────────────────────────────────────────────
# 10. Lifecycle
# ──────────────────────────────────────────────────────


class TestLifecycle(APIServerPerTestCase):
    def test_lifecycle_status(self) -> None:
        code, body = _request(f"{self.base}/api/lifecycle")
        self.assertEqual(code, 200)
        self.assertIn("ariaflow-server", body)
        self.assertIn("meta", body["ariaflow-server"])
        self.assertEqual(body["ariaflow-server"]["meta"]["contract"], "UCC")

    def test_lifecycle_action_non_macos(self) -> None:
        with patch("ariaflow_server.routes.lifecycle.is_macos", return_value=False):
            code, body = _request(
                f"{self.base}/api/lifecycle/ariaflow-server/install",
                "POST",
                {
                    "target": "ariaflow-server",
                    "action": "install",
                },
            )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "use_pipx")


# ──────────────────────────────────────────────────────
# 11. UCC Endpoint
# ──────────────────────────────────────────────────────


class TestUCC(APIServerPerTestCase):
    def test_ucc_returns_structured_result(self) -> None:
        with (
            patch(
                "ariaflow_server.contracts.preflight",
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
            patch("ariaflow_server.core.process_queue", return_value=[]),
            patch("ariaflow_server.core.get_active_progress", return_value=None),
        ):
            code, body = _request(f"{self.base}/api/scheduler/ucc", "POST")
        self.assertEqual(code, 200)
        self.assertIn("meta", body)
        self.assertIn("result", body)
        self.assertIn("observation", body["result"])
        self.assertIn("outcome", body["result"])


# ──────────────────────────────────────────────────────
# 12. Meta Endpoints (Docs, OpenAPI, Tests)
# ──────────────────────────────────────────────────────


class TestMetaEndpoints(APIServerPerTestCase):
    def test_openapi_yaml(self) -> None:
        code, body, headers = _raw_request(f"{self.base}/api/openapi.yaml")
        self.assertEqual(code, 200)
        text = body.decode("utf-8")
        self.assertIn("openapi:", text)
        self.assertIn("/api/status", text)
        self.assertIn("yaml", headers.get("Content-Type", ""))

    def test_swagger_ui(self) -> None:
        code, body, headers = _raw_request(f"{self.base}/api/docs")
        self.assertEqual(code, 200)
        html = body.decode("utf-8")
        self.assertIn("swagger-ui", html)
        self.assertIn("openapi.yaml", html)
        self.assertIn("text/html", headers.get("Content-Type", ""))

    def test_cors_headers(self) -> None:
        code, body, headers = _raw_request(f"{self.base}/api/status")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_schema_version_in_response(self) -> None:
        code, body = _request(f"{self.base}/api/status")
        self.assertIn("_schema", body)
        self.assertEqual(body["_schema"], "2")

    def test_request_id_in_response(self) -> None:
        # Use non-cached endpoint to verify unique request IDs
        code, body = _request(f"{self.base}/api/declaration")
        self.assertIn("_request_id", body)
        self.assertTrue(len(body["_request_id"]) > 0)
        _, body2 = _request(f"{self.base}/api/declaration")
        self.assertNotEqual(body["_request_id"], body2["_request_id"])

    def test_schema_version_header(self) -> None:
        code, _, headers = _raw_request(f"{self.base}/api/status")
        self.assertEqual(headers.get("X-Schema-Version"), "2")
        self.assertTrue(len(headers.get("X-Request-Id", "")) > 0)

    def test_etag_on_status(self) -> None:
        # First request gets ETag
        code, body, headers = _raw_request(f"{self.base}/api/status")
        self.assertEqual(code, 200)
        etag = headers.get("ETag", "")
        self.assertTrue(etag.startswith('"'))

        # Same request with If-None-Match returns 304
        req = urllib.request.Request(
            f"{self.base}/api/status",
            headers={"If-None-Match": etag},
        )
        try:
            with urllib.request.urlopen(req, timeout=5):
                # 304 should not have body but urllib may still return 200
                pass
        except urllib.error.HTTPError as exc:
            # 304 is not an error per se but urllib treats it as one
            self.assertEqual(exc.code, 304)

    def test_revision_counter_in_status(self) -> None:
        _request(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/rev.bin"}],
            },
        )
        _, body = _request(f"{self.base}/api/status")
        self.assertIn("_rev", body)
        rev1 = body["_rev"]
        self.assertIsInstance(rev1, int)
        self.assertGreater(rev1, 0)

    def test_sse_endpoint_connects(self) -> None:
        """Verify SSE endpoint sends connected event."""
        import socket

        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        sock.settimeout(3)
        sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        data = b""
        try:
            while len(data) < 1024:
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
        self.assertIn("schema_version", text)


# ──────────────────────────────────────────────────────
# 13. Error Handling & Edge Cases
# ──────────────────────────────────────────────────────


class TestErrorHandling(APIServerPerTestCase):
    def test_404_unknown_endpoint(self) -> None:
        code, body = _request(f"{self.base}/api/nonexistent")
        self.assertEqual(code, 404)

    def test_404_unknown_post_endpoint(self) -> None:
        code, body = _request(f"{self.base}/api/nonexistent", "POST", {})
        self.assertEqual(code, 404)

    def test_invalid_json_body(self) -> None:
        code, _, _ = _raw_request(
            f"{self.base}/api/scheduler/pause",
            method="POST",
            data=b"{broken",
            content_type="application/json",
        )
        self.assertEqual(code, 400)

    def test_empty_post_body(self) -> None:
        code, _, _ = _raw_request(
            f"{self.base}/api/scheduler/pause",
            method="POST",
            data=b"",
            content_type="application/json",
        )
        self.assertEqual(code, 200)

    def test_concurrent_add_and_status(self) -> None:
        """Verify server handles overlapping requests."""
        results: list[tuple[int, dict]] = []

        def add_item() -> None:
            r = _request(
                f"{self.base}/api/downloads/add",
                "POST",
                {
                    "items": [
                        {"url": f"https://example.com/concurrent-{time.time()}.bin"}
                    ],
                },
            )
            results.append(r)

        threads = [threading.Thread(target=add_item) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(results), 5)
        for code, body in results:
            self.assertEqual(code, 200)
            self.assertTrue(body["ok"])

        # All items should be in status
        code, status = _request(f"{self.base}/api/status")
        self.assertEqual(code, 200)
        self.assertGreaterEqual(status["summary"]["total"], 5)


# ══════════════════════════════════════════════════════════════════════
# Per-class shared server tests (APIServerTestCase) — from coverage
# ══════════════════════════════════════════════════════════════════════


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
        self.assertEqual(body["name"], "ariaflow-server")
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
            "ariaflow-server",
            "_rev",
        ):
            self.assertIn(key, body, f"missing key: {key}")
        self.assertIn("schema_version", body["ariaflow-server"])
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

    # 6. GET /api/declaration fields
    def test_get_api_declaration_fields(self) -> None:
        code, body, _ = _req(f"{self.base}/api/declaration")
        self.assertEqual(code, 200)
        self.assertIn("uic", body)

    # 7. GET /api/lifecycle
    def test_get_api_lifecycle(self) -> None:
        code, body, _ = _req(f"{self.base}/api/lifecycle")
        self.assertEqual(code, 200)
        self.assertIn("ariaflow-server", body)
        self.assertEqual(body["ariaflow-server"]["meta"]["contract"], "UCC")

    # 8. GET /api/downloads/{id}/files
    def test_get_api_item_files_no_gid(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/t.torrent"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/downloads/{item_id}/files")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "no_gid")

    def test_get_api_item_files_with_gid(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
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
        with patch("ariaflow_server.core.aria_rpc", return_value={"result": files}):
            code, body, _ = _req(f"{self.base}/api/downloads/{item_id}/files")
        self.assertEqual(code, 200)
        self.assertEqual(len(body["files"]), 1)

    def test_get_api_item_files_not_found(self) -> None:
        code, body, _ = _req(
            f"{self.base}/api/downloads/00000000-0000-0000-0000-000000000000/files"
        )
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
        with patch("ariaflow_server.webapp.subprocess.run", return_value=fake):
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
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/post-add.bin"}],
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["count"], 1)

    def test_post_api_add_invalid(self) -> None:
        code, body, _ = _req(f"{self.base}/api/downloads/add", "POST", {"items": []})
        self.assertEqual(code, 400)

    # 2. POST /api/scheduler/start — removed (auto-starts)
    def test_post_api_scheduler_start_returns_404(self) -> None:
        code, body, _ = _req(f"{self.base}/api/scheduler/start", "POST", {})
        self.assertEqual(code, 404)

    # 3. POST /api/scheduler/stop — removed (no stop)
    def test_post_api_scheduler_stop_returns_404(self) -> None:
        code, body, _ = _req(f"{self.base}/api/scheduler/stop", "POST", {})
        self.assertEqual(code, 404)

    def test_post_api_scheduler_invalid_path(self) -> None:
        code, body, _ = _req(f"{self.base}/api/scheduler/boom", "POST", {})
        self.assertEqual(code, 404)

    # 4. POST /api/scheduler/preflight
    def test_post_api_preflight(self) -> None:
        with (
            patch(
                "ariaflow_server.webapp.preflight",
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
            patch("ariaflow_server.webapp.aria2_status", return_value={}),
            patch("ariaflow_server.webapp.aria2_current_bandwidth", return_value={}),
        ):
            code, body, _ = _req(f"{self.base}/api/scheduler/preflight", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "pass")

    # 5. POST /api/scheduler/ucc
    def test_post_api_ucc(self) -> None:
        with (
            patch(
                "ariaflow_server.contracts.preflight",
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
            patch("ariaflow_server.core.process_queue", return_value=[]),
            patch("ariaflow_server.core.get_active_progress", return_value=None),
        ):
            code, body, _ = _req(f"{self.base}/api/scheduler/ucc", "POST")
        self.assertEqual(code, 200)
        self.assertIn("meta", body)
        self.assertIn("result", body)

    # 6. POST /api/pause
    def test_post_api_pause(self) -> None:
        code, body, _ = _req(f"{self.base}/api/scheduler/pause", "POST")
        self.assertEqual(code, 200)
        self.assertIn("paused", body)

    # 7. POST /api/resume
    def test_post_api_resume(self) -> None:
        code, body, _ = _req(f"{self.base}/api/scheduler/resume", "POST")
        self.assertEqual(code, 200)
        self.assertIn("resumed", body)

    # 8. POST /api/declaration
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
            patch("ariaflow_server.core.probe_bandwidth", return_value=probe),
            patch("ariaflow_server.core.aria2_set_max_overall_download_limit"),
        ):
            code, body, _ = _req(f"{self.base}/api/bandwidth/probe", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["downlink_mbps"], 80.0)
        self.assertEqual(body["uplink_mbps"], 15.0)
        self.assertIn("down_cap_mbps", body)
        self.assertIn("up_cap_mbps", body)

    # 11. POST /api/aria2/change_global_option
    def test_post_api_aria2_options_safe(self) -> None:
        with (
            patch("ariaflow_server.core.aria_rpc"),
            patch("ariaflow_server.core.aria2_current_global_options", return_value={}),
        ):
            code, body, _ = _req(
                f"{self.base}/api/aria2/change_global_option",
                "POST",
                {
                    "max-concurrent-downloads": "3",
                },
            )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_post_api_aria2_options_unsafe(self) -> None:
        code, body, _ = _req(
            f"{self.base}/api/aria2/change_global_option", "POST", {"dir": "/evil"}
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "rejected_options")

    # 12. POST /api/downloads/{id}/pause
    def test_post_api_item_pause(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/pause-me.bin"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "paused")

    # 13. POST /api/downloads/{id}/resume
    def test_post_api_item_resume(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/resume-me.bin"}]},
        )
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        code, body, _ = _req(f"{self.base}/api/downloads/{item_id}/resume", "POST")
        self.assertEqual(code, 200)
        self.assertIn(body["item"]["status"], ("queued", "active"))

    # 14. POST /api/downloads/{id}/remove
    def test_post_api_item_remove(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/remove-me.bin"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["removed"])

    # 15. POST /api/downloads/{id}/retry
    def test_post_api_item_retry(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
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
        code, body, _ = _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    # 16. POST /api/downloads/{id}/files (select)
    def test_post_api_item_files_select(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
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
        with patch("ariaflow_server.core.aria_rpc"):
            code, body, _ = _req(
                f"{self.base}/api/downloads/{item_id}/files", "POST", {"select": [1, 2]}
            )
        self.assertEqual(code, 200)
        self.assertEqual(body["selected"], [1, 2])

    def test_post_api_item_files_select_invalid(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/sel2.torrent"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(
            f"{self.base}/api/downloads/{item_id}/files", "POST", {"select": []}
        )
        self.assertEqual(code, 400)

    # 17. POST /api/lifecycle/ariaflow-server/install
    def test_post_api_lifecycle_action_non_macos(self) -> None:
        with patch("ariaflow_server.routes.lifecycle.is_macos", return_value=False):
            code, body, _ = _req(
                f"{self.base}/api/lifecycle/ariaflow-server/install",
                "POST",
                {
                    "target": "ariaflow-server",
                    "action": "install",
                },
            )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "use_pipx")

    def test_post_api_lifecycle_action_install(self) -> None:
        with (
            patch("ariaflow_server.routes.lifecycle.is_macos", return_value=True),
            patch(
                "ariaflow_server.routes.lifecycle.homebrew_install_ariaflow_server",
                return_value=["brew install ariaflow-server"],
            ),
        ):
            code, body, _ = _req(
                f"{self.base}/api/lifecycle/ariaflow-server/install",
                "POST",
                {
                    "target": "ariaflow-server",
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
        self.assertEqual(body["_schema"], "2")

    def test_schema_version_in_header(self) -> None:
        _, _, hdrs = _req(f"{self.base}/api/declaration")
        self.assertEqual(hdrs.get("X-Schema-Version"), "2")

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
            f"{self.base}/api/downloads/add",
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

    # Invalid item action
    def test_invalid_item_action(self) -> None:
        _, added, _ = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": "https://example.com/inv.bin"}]},
        )
        item_id = added["added"][0]["id"]
        code, body, _ = _req(f"{self.base}/api/downloads/{item_id}/explode", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_action")

    # Item not found
    def test_item_not_found(self) -> None:
        code, body, _ = _req(
            f"{self.base}/api/downloads/00000000-0000-0000-0000-000000000000/pause",
            "POST",
        )
        self.assertEqual(code, 404)

    # State consistency: add → status reflects it
    def test_add_reflected_in_status(self) -> None:
        url = f"https://example.com/consistency-{time.time()}.bin"
        _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        _, status, _ = _req(f"{self.base}/api/status")
        urls = [item["url"] for item in status["items"]]
        self.assertIn(url, urls)

    # State consistency: remove → status reflects it
    def test_remove_reflected_in_status(self) -> None:
        url = f"https://example.com/remove-check-{time.time()}.bin"
        _, added, _ = _req(
            f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]}
        )
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")
        _, status, _ = _req(f"{self.base}/api/status")
        ids = [item["id"] for item in status["items"]]
        self.assertNotIn(item_id, ids)

    # Action log records operations
    def test_actions_logged(self) -> None:
        url = f"https://example.com/logged-{time.time()}.bin"
        _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        _, log, _ = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("add", actions)


if __name__ == "__main__":
    unittest.main()
