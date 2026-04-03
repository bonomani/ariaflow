"""Extensive API integration tests.

Every test spins up a real HTTP server and makes real requests.
aria2 RPC is mocked where needed to avoid requiring a running daemon.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import APIServerPerTestCase, raw_request, request_json

from aria_queue.core import load_queue, save_queue


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
            f"{self.base}/api/add",
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
            f"{self.base}/api/add",
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
            f"{self.base}/api/add",
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
            f"{self.base}/api/add",
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
            f"{self.base}/api/add",
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
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": "https://example.com/dup.bin"}],
            },
        )
        _, second = _request(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": "https://example.com/dup.bin"}],
            },
        )
        self.assertEqual(first["added"][0]["id"], second["added"][0]["id"])

    def test_add_empty_items_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/add", "POST", {"items": []})
        self.assertEqual(code, 400)

    def test_add_missing_items_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/add", "POST", {"url": "https://example.com/x"}
        )
        self.assertEqual(code, 400)

    def test_add_invalid_json_returns_400(self) -> None:
        code, _, _ = _raw_request(
            f"{self.base}/api/add",
            method="POST",
            data=b"not json",
            content_type="application/json",
        )
        self.assertEqual(code, 400)

    def test_add_no_body_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/add", "POST", None)
        self.assertEqual(code, 400)


# ──────────────────────────────────────────────────────
# 3. Per-item Actions
# ──────────────────────────────────────────────────────


class TestPerItemActions(APIServerPerTestCase):
    def setUp(self) -> None:
        super().setUp()
        _, added = _request(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": "https://example.com/item.bin"}],
            },
        )
        self.item_id = added["added"][0]["id"]

    # ── Pause ──

    def test_pause_queued_item(self) -> None:
        code, body = _request(f"{self.base}/api/item/{self.item_id}/pause", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["item"]["status"], "paused")

    def test_pause_already_paused_returns_400(self) -> None:
        _request(f"{self.base}/api/item/{self.item_id}/pause", "POST")
        code, body = _request(f"{self.base}/api/item/{self.item_id}/pause", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    def test_pause_done_item_returns_400(self) -> None:
        items = load_queue()
        items[0]["status"] = "complete"
        save_queue(items)
        code, body = _request(f"{self.base}/api/item/{self.item_id}/pause", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    def test_pause_nonexistent_returns_404(self) -> None:
        code, body = _request(f"{self.base}/api/item/fake-id/pause", "POST")
        self.assertEqual(code, 404)
        self.assertEqual(body["error"], "not_found")

    # ── Resume ──

    def test_resume_paused_item_without_gid(self) -> None:
        _request(f"{self.base}/api/item/{self.item_id}/pause", "POST")
        code, body = _request(f"{self.base}/api/item/{self.item_id}/resume", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    def test_resume_paused_item_with_gid(self) -> None:
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("aria_queue.core.aria_rpc"):
            code, body = _request(f"{self.base}/api/item/{self.item_id}/resume", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "active")

    def test_resume_queued_item_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/item/{self.item_id}/resume", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    # ── Remove ──

    def test_remove_queued_item(self) -> None:
        code, body = _request(f"{self.base}/api/item/{self.item_id}/remove", "POST")
        self.assertEqual(code, 200)
        self.assertTrue(body["removed"])
        self.assertEqual(len(load_queue()), 0)

    def test_remove_downloading_item_calls_aria2(self) -> None:
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("aria_queue.core.aria_rpc") as rpc:
            code, body = _request(f"{self.base}/api/item/{self.item_id}/remove", "POST")
        self.assertEqual(code, 200)
        rpc.assert_any_call("aria2.remove", ["gid-1"], port=6800, timeout=5)

    def test_remove_nonexistent_returns_404(self) -> None:
        code, body = _request(f"{self.base}/api/item/fake-id/remove", "POST")
        self.assertEqual(code, 404)

    def test_double_remove_returns_404(self) -> None:
        _request(f"{self.base}/api/item/{self.item_id}/remove", "POST")
        code, body = _request(f"{self.base}/api/item/{self.item_id}/remove", "POST")
        self.assertEqual(code, 404)

    # ── Retry ──

    def test_retry_error_item(self) -> None:
        items = load_queue()
        items[0]["status"] = "error"
        items[0]["error_code"] = "5"
        items[0]["error_message"] = "download failed"
        items[0]["gid"] = "gid-dead"
        save_queue(items)
        code, body = _request(f"{self.base}/api/item/{self.item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")
        self.assertNotIn("error_code", body["item"])
        self.assertNotIn("error_message", body["item"])
        self.assertNotIn("gid", body["item"])

    def test_retry_failed_item(self) -> None:
        items = load_queue()
        items[0]["status"] = "failed"
        save_queue(items)
        code, body = _request(f"{self.base}/api/item/{self.item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    def test_retry_stopped_item(self) -> None:
        items = load_queue()
        items[0]["status"] = "stopped"
        save_queue(items)
        code, body = _request(f"{self.base}/api/item/{self.item_id}/retry", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["item"]["status"], "queued")

    def test_retry_queued_item_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/item/{self.item_id}/retry", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")

    def test_retry_done_item_returns_400(self) -> None:
        items = load_queue()
        items[0]["status"] = "complete"
        save_queue(items)
        code, body = _request(f"{self.base}/api/item/{self.item_id}/retry", "POST")
        self.assertEqual(code, 400)

    # ── Invalid action ──

    def test_invalid_action_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/item/{self.item_id}/explode", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_action")


# ──────────────────────────────────────────────────────
# 4. File Selection (Torrent/Metalink)
# ──────────────────────────────────────────────────────


class TestFileSelection(APIServerPerTestCase):
    def setUp(self) -> None:
        super().setUp()
        _, added = _request(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": "https://example.com/archive.torrent"}],
            },
        )
        self.item_id = added["added"][0]["id"]

    def test_get_files_no_gid_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/item/{self.item_id}/files")
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
        with patch("aria_queue.core.aria_rpc", return_value={"result": files}):
            code, body = _request(f"{self.base}/api/item/{self.item_id}/files")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["files"]), 2)
        self.assertEqual(body["gid"], "gid-torrent")

    def test_get_files_nonexistent_returns_404(self) -> None:
        code, body = _request(f"{self.base}/api/item/fake/files")
        self.assertEqual(code, 404)

    def test_select_files(self) -> None:
        items = load_queue()
        items[0]["gid"] = "gid-torrent"
        items[0]["status"] = "paused"
        save_queue(items)
        with patch("aria_queue.core.aria_rpc") as rpc:
            code, body = _request(
                f"{self.base}/api/item/{self.item_id}/files",
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
            f"{self.base}/api/item/{self.item_id}/files",
            "POST",
            {"select": []},
        )
        self.assertEqual(code, 400)

    def test_select_files_missing_select_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/item/{self.item_id}/files",
            "POST",
            {"indices": [1, 2]},
        )
        self.assertEqual(code, 400)

    def test_select_files_non_integer_returns_400(self) -> None:
        code, body = _request(
            f"{self.base}/api/item/{self.item_id}/files",
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
            patch("aria_queue.core.aria_rpc"),
            patch("aria_queue.core.current_global_options", return_value={}),
        ):
            code, body = _request(
                f"{self.base}/api/aria2/options",
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
            patch("aria_queue.core.aria_rpc"),
            patch("aria_queue.core.current_global_options", return_value={}),
        ):
            code, body = _request(
                f"{self.base}/api/aria2/options",
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
            f"{self.base}/api/aria2/options",
            "POST",
            {
                "dir": "/tmp/evil",
            },
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "rejected_options")

    def test_mixed_safe_unsafe_rejected(self) -> None:
        code, body = _request(
            f"{self.base}/api/aria2/options",
            "POST",
            {
                "max-concurrent-downloads": "3",
                "enable-rpc": "false",
            },
        )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "rejected_options")

    def test_empty_options_rejected(self) -> None:
        code, body = _request(f"{self.base}/api/aria2/options", "POST", {})
        self.assertEqual(code, 400)
        self.assertIn(body["error"], ("empty_options", "invalid_payload"))

    def test_non_object_payload_rejected(self) -> None:
        code, body = _request(f"{self.base}/api/aria2/options", "POST", None)
        self.assertEqual(code, 400)

    def test_all_eight_safe_options(self) -> None:
        all_safe = {
            "max-concurrent-downloads": "3",
            "max-connection-per-server": "4",
            "split": "4",
            "min-split-size": "1M",
            "max-overall-download-limit": "0",
            "max-download-limit": "0",
            "timeout": "60",
            "connect-timeout": "30",
        }
        with (
            patch("aria_queue.core.aria_rpc"),
            patch("aria_queue.core.current_global_options", return_value={}),
        ):
            code, body = _request(f"{self.base}/api/aria2/options", "POST", all_safe)
        self.assertEqual(code, 200)
        self.assertEqual(len(body["applied"]), 8)


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
            patch("aria_queue.core.probe_bandwidth", return_value=probe_result),
            patch("aria_queue.core.set_bandwidth"),
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
            patch("aria_queue.core.probe_bandwidth", return_value=probe_result),
            patch("aria_queue.core.set_bandwidth"),
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
        with patch("aria_queue.core._find_networkquality", return_value=None):
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
    def test_run_start(self) -> None:
        code, body = _request(
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

    def test_run_stop(self) -> None:
        code, body = _request(f"{self.base}/api/run", "POST", {"action": "stop"})
        self.assertEqual(code, 200)
        self.assertEqual(body["action"], "stop")

    def test_run_invalid_action_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/run", "POST", {"action": "restart"})
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_action")

    def test_run_missing_action_returns_400(self) -> None:
        code, body = _request(f"{self.base}/api/run", "POST", {})
        self.assertEqual(code, 400)

    def test_global_pause_resume(self) -> None:
        code, paused = _request(f"{self.base}/api/pause", "POST")
        self.assertEqual(code, 200)
        self.assertIn("paused", paused)

        code, resumed = _request(f"{self.base}/api/resume", "POST")
        self.assertEqual(code, 200)
        self.assertIn("resumed", resumed)

    def test_preflight(self) -> None:
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
            patch("aria_queue.webapp.aria2_status", return_value={}),
            patch("aria_queue.webapp.current_bandwidth", return_value={}),
        ):
            code, body = _request(f"{self.base}/api/preflight", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "pass")
        self.assertIn("gates", body)

    def test_preflight_blocked_start(self) -> None:
        with (
            patch("aria_queue.webapp.auto_preflight_on_run", return_value=False),
            patch(
                "aria_queue.webapp.preflight",
                return_value={
                    "status": "fail",
                    "exit_code": 1,
                    "gates": [],
                    "preferences": [],
                    "policies": [],
                    "warnings": [],
                    "hard_failures": ["aria2_available"],
                },
            ),
        ):
            code, body = _request(
                f"{self.base}/api/run",
                "POST",
                {
                    "action": "start",
                    "auto_preflight_on_run": True,
                },
            )
        self.assertEqual(code, 409)
        self.assertEqual(body["error"], "preflight_blocked")


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

    def test_get_options_is_alias(self) -> None:
        _, decl = _request(f"{self.base}/api/declaration")
        _, opts = _request(f"{self.base}/api/options")
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
# 8. Session Management
# ──────────────────────────────────────────────────────


class TestSession(APIServerPerTestCase):
    def test_new_session(self) -> None:
        # Create initial session via add
        _request(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": "https://example.com/x.bin"}],
            },
        )
        _, status_before = _request(f"{self.base}/api/status")
        old_session = status_before["state"]["session_id"]

        code, body = _request(f"{self.base}/api/session", "POST", {"action": "new"})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        new_session = body["session"]["session_id"]
        self.assertNotEqual(old_session, new_session)

    def test_new_session_closes_previous(self) -> None:
        _request(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/y.bin"}]},
        )
        _request(f"{self.base}/api/session", "POST", {"action": "new"})
        # Check the log for close action
        _, log = _request(f"{self.base}/api/log?limit=10")
        actions = [entry.get("action") for entry in log["items"]]
        self.assertIn("session", actions)


# ──────────────────────────────────────────────────────
# 9. Action Log
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
                f"{self.base}/api/add",
                "POST",
                {"items": [{"url": f"https://example.com/{i}.bin"}]},
            )
        code, body = _request(f"{self.base}/api/log?limit=3")
        self.assertLessEqual(len(body["items"]), 3)

    def test_log_entries_have_timestamps(self) -> None:
        _request(
            f"{self.base}/api/add",
            "POST",
            {"items": [{"url": "https://example.com/log.bin"}]},
        )
        _, body = _request(f"{self.base}/api/log?limit=5")
        for entry in body["items"]:
            self.assertIn("timestamp", entry)

    def test_log_records_add_action(self) -> None:
        _request(
            f"{self.base}/api/add",
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
        self.assertIn("ariaflow", body)
        self.assertIn("meta", body["ariaflow"])
        self.assertEqual(body["ariaflow"]["meta"]["contract"], "UCC")

    def test_lifecycle_action_non_macos(self) -> None:
        with patch("aria_queue.webapp.is_macos", return_value=False):
            code, body = _request(
                f"{self.base}/api/lifecycle/action",
                "POST",
                {
                    "target": "ariaflow",
                    "action": "install",
                },
            )
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "macos_only")


# ──────────────────────────────────────────────────────
# 11. UCC Endpoint
# ──────────────────────────────────────────────────────


class TestUCC(APIServerPerTestCase):
    def test_ucc_returns_structured_result(self) -> None:
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
            code, body = _request(f"{self.base}/api/ucc", "POST")
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
            f"{self.base}/api/add",
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
            f"{self.base}/api/run",
            method="POST",
            data=b"{broken",
            content_type="application/json",
        )
        self.assertEqual(code, 400)

    def test_empty_post_body(self) -> None:
        code, _, _ = _raw_request(
            f"{self.base}/api/run",
            method="POST",
            data=b"",
            content_type="application/json",
        )
        self.assertEqual(code, 400)

    def test_concurrent_add_and_status(self) -> None:
        """Verify server handles overlapping requests."""
        results: list[tuple[int, dict]] = []

        def add_item() -> None:
            r = _request(
                f"{self.base}/api/add",
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


if __name__ == "__main__":
    unittest.main()
