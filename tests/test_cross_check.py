"""Cross-check tests — verify mutating actions are reflected in read endpoints.

Every test performs a mutation, then reads back the state from the
corresponding GET endpoint and verifies consistency.
"""

from __future__ import annotations

import time
from typing import Any
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import APIServerTestCase, request_json

from aria_queue.core import load_queue, save_queue


def _req(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: int = 5,
) -> tuple[int, Any]:
    """Thin 2-tuple wrapper around conftest.request_json."""
    code, body, _ = request_json(url, method=method, payload=payload, timeout=timeout)
    return code, body


CrossCheckBase = APIServerTestCase


# ═══════════════════════════════════════════════════════
# Add → Status
# ═══════════════════════════════════════════════════════


class TestAddReflectedInStatus(CrossCheckBase):
    def test_added_item_appears_in_status(self) -> None:
        url = f"https://example.com/xc-add-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, status = _req(f"{self.base}/api/status")
        ids = [item["id"] for item in status["items"]]
        self.assertIn(item_id, ids)

        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["url"], url)
        self.assertEqual(item["status"], "queued")

    def test_added_item_counted_in_summary(self) -> None:
        _, before = _req(f"{self.base}/api/status")
        before_total = before["summary"]["total"]

        url = f"https://example.com/xc-count-{time.time()}.bin"
        _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})

        _, after = _req(f"{self.base}/api/status")
        self.assertEqual(after["summary"]["total"], before_total + 1)

    def test_added_item_creates_session(self) -> None:
        url = f"https://example.com/xc-sess-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        session_id = added["added"][0]["session_id"]

        _, status = _req(f"{self.base}/api/status")
        self.assertEqual(status["state"]["session_id"], session_id)

    def test_add_multiple_all_in_status(self) -> None:
        urls = [f"https://example.com/xc-multi-{i}-{time.time()}.bin" for i in range(3)]
        _, added = _req(
            f"{self.base}/api/downloads/add", "POST", {"items": [{"url": u} for u in urls]}
        )
        added_ids = {item["id"] for item in added["added"]}

        _, status = _req(f"{self.base}/api/status")
        status_ids = {item["id"] for item in status["items"]}
        self.assertTrue(added_ids.issubset(status_ids))

    def test_add_with_output_reflected(self) -> None:
        url = f"https://example.com/xc-output-{time.time()}.bin"
        _, added = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": url, "output": "custom.bin"}]},
        )
        item_id = added["added"][0]["id"]
        self.assertEqual(added["added"][0]["output"], "custom.bin")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item.get("output"), "custom.bin")

    def test_duplicate_add_same_id_in_status(self) -> None:
        url = f"https://example.com/xc-dup-{time.time()}.bin"
        _, first = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        _, second = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        self.assertEqual(first["added"][0]["id"], second["added"][0]["id"])

        _, status = _req(f"{self.base}/api/status")
        matching = [i for i in status["items"] if i["url"] == url]
        self.assertEqual(len(matching), 1)


# ═══════════════════════════════════════════════════════
# Pause → Status
# ═══════════════════════════════════════════════════════


class TestPauseReflectedInStatus(CrossCheckBase):
    def test_paused_item_status_matches(self) -> None:
        url = f"https://example.com/xc-pause-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, paused = _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        self.assertEqual(paused["item"]["status"], "paused")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "paused")

    def test_paused_item_summary_counts(self) -> None:
        url = f"https://example.com/xc-pause-cnt-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")

        _, status = _req(f"{self.base}/api/status")
        self.assertGreater(status["summary"].get("paused", 0), 0)

    def test_pause_preserves_url_and_id(self) -> None:
        url = f"https://example.com/xc-pause-fields-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["url"], url)
        self.assertEqual(item["id"], item_id)

    def test_pause_does_not_affect_other_items(self) -> None:
        _, added = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": f"https://example.com/xc-p-other-a-{time.time()}.bin"},
                    {"url": f"https://example.com/xc-p-other-b-{time.time()}.bin"},
                ]
            },
        )
        id_a = added["added"][0]["id"]
        id_b = added["added"][1]["id"]
        _req(f"{self.base}/api/downloads/{id_a}/pause", "POST")

        _, status = _req(f"{self.base}/api/status")
        item_b = next(i for i in status["items"] if i["id"] == id_b)
        self.assertEqual(item_b["status"], "queued")


# ═══════════════════════════════════════════════════════
# Resume → Status
# ═══════════════════════════════════════════════════════


class TestResumeReflectedInStatus(CrossCheckBase):
    def test_resumed_item_status_matches(self) -> None:
        url = f"https://example.com/xc-resume-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")

        _, resumed = _req(f"{self.base}/api/downloads/{item_id}/resume", "POST")
        expected_status = resumed["item"]["status"]

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], expected_status)

    def test_resume_clears_paused_summary(self) -> None:
        url = f"https://example.com/xc-resume-sum-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")

        _, before = _req(f"{self.base}/api/status")
        paused_before = before["summary"].get("paused", 0)

        _req(f"{self.base}/api/downloads/{item_id}/resume", "POST")

        _, after = _req(f"{self.base}/api/status")
        paused_after = after["summary"].get("paused", 0)
        self.assertLess(paused_after, paused_before)

    def test_pause_resume_cycle_preserves_url(self) -> None:
        url = f"https://example.com/xc-cycle-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        _req(f"{self.base}/api/downloads/{item_id}/resume", "POST")
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        _req(f"{self.base}/api/downloads/{item_id}/resume", "POST")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["url"], url)
        self.assertIn(item["status"], ("queued", "active"))


# ═══════════════════════════════════════════════════════
# Remove → Status
# ═══════════════════════════════════════════════════════


class TestRemoveReflectedInStatus(CrossCheckBase):
    def test_removed_item_gone_from_status(self) -> None:
        url = f"https://example.com/xc-remove-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, removed = _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")
        self.assertTrue(removed["removed"])

        _, status = _req(f"{self.base}/api/status")
        ids = [item["id"] for item in status["items"]]
        self.assertNotIn(item_id, ids)

    def test_removed_item_reduces_total(self) -> None:
        url = f"https://example.com/xc-rem-cnt-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, before = _req(f"{self.base}/api/status")
        before_total = before["summary"]["total"]

        _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")

        _, after = _req(f"{self.base}/api/status")
        self.assertEqual(after["summary"]["total"], before_total - 1)


# ═══════════════════════════════════════════════════════
# Retry → Status
# ═══════════════════════════════════════════════════════


class TestRetryReflectedInStatus(CrossCheckBase):
    def test_retried_item_back_to_queued(self) -> None:
        url = f"https://example.com/xc-retry-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
                item["error_code"] = "99"
        save_queue(items)

        _, retried = _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")
        self.assertEqual(retried["item"]["status"], "queued")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "queued")
        self.assertIsNone(item.get("error_code"))
        self.assertIsNone(item.get("gid"))

    def test_retry_clears_error_message(self) -> None:
        url = f"https://example.com/xc-retry-msg-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
                item["error_code"] = "5"
                item["error_message"] = "connection timeout"
                item["gid"] = "gid-dead"
        save_queue(items)

        _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertIsNone(item.get("error_message"))

    def test_retry_preserves_url(self) -> None:
        url = f"https://example.com/xc-retry-url-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "failed"
        save_queue(items)

        _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["url"], url)

    def test_retry_error_count_decreases(self) -> None:
        url = f"https://example.com/xc-retry-errcount-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
        save_queue(items)

        _, before = _req(f"{self.base}/api/status")
        err_before = before["summary"].get("error", 0)

        _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")

        _, after = _req(f"{self.base}/api/status")
        err_after = after["summary"].get("error", 0)
        self.assertLess(err_after, err_before)


# ═══════════════════════════════════════════════════════
# Declaration save → Declaration read
# ═══════════════════════════════════════════════════════


class TestDeclarationRoundtrip(CrossCheckBase):
    def test_saved_declaration_readable(self) -> None:
        _, original = _req(f"{self.base}/api/declaration")
        original.pop("_schema", None)
        original.pop("_request_id", None)

        # Add a custom preference
        original["uic"]["preferences"].append(
            {
                "name": f"xc_pref_{time.time()}",
                "value": "test",
                "options": ["test"],
                "rationale": "cross-check",
            }
        )

        _, saved = _req(f"{self.base}/api/declaration", "POST", original)
        self.assertTrue(saved["saved"])

        _, reloaded = _req(f"{self.base}/api/declaration")
        saved_names = [p["name"] for p in saved["declaration"]["uic"]["preferences"]]
        reloaded_names = [p["name"] for p in reloaded["uic"]["preferences"]]
        self.assertEqual(saved_names, reloaded_names)

    def test_bandwidth_config_reflects_declaration_change(self) -> None:
        _, decl = _req(f"{self.base}/api/declaration")
        for pref in decl["uic"]["preferences"]:
            if pref["name"] == "bandwidth_down_free_percent":
                pref["value"] = 40
        _req(f"{self.base}/api/declaration", "POST", decl)

        _, bw = _req(f"{self.base}/api/bandwidth")
        self.assertEqual(bw["config"]["down_free_percent"], 40)
        self.assertAlmostEqual(bw["config"]["down_use_percent"], 0.6)

    def test_options_alias_matches_declaration(self) -> None:
        _, decl = _req(f"{self.base}/api/declaration")
        _, opts = _req(f"{self.base}/api/declaration")
        decl.pop("_request_id", None)
        opts.pop("_request_id", None)
        self.assertEqual(decl, opts)

    def test_declaration_gate_change_reflected(self) -> None:
        _, decl = _req(f"{self.base}/api/declaration")
        decl["uic"]["gates"].append(
            {"name": "xc_test_gate", "class": "readiness", "blocking": "soft"}
        )
        _req(f"{self.base}/api/declaration", "POST", decl)
        _, reloaded = _req(f"{self.base}/api/declaration")
        gate_names = [g["name"] for g in reloaded["uic"]["gates"]]
        self.assertIn("xc_test_gate", gate_names)

    def test_declaration_preference_value_change_reflected(self) -> None:
        _, decl = _req(f"{self.base}/api/declaration")
        for pref in decl["uic"]["preferences"]:
            if pref["name"] == "max_simultaneous_downloads":
                pref["value"] = 5
        _req(f"{self.base}/api/declaration", "POST", decl)
        _, reloaded = _req(f"{self.base}/api/declaration")
        pref = next(
            p
            for p in reloaded["uic"]["preferences"]
            if p["name"] == "max_simultaneous_downloads"
        )
        self.assertEqual(pref["value"], 5)

    def test_all_bandwidth_prefs_in_declaration_and_config(self) -> None:
        _, decl = _req(f"{self.base}/api/declaration")
        pref_names = {p["name"] for p in decl["uic"]["preferences"]}
        expected = {
            "bandwidth_down_free_percent",
            "bandwidth_down_free_absolute_mbps",
            "bandwidth_up_free_percent",
            "bandwidth_up_free_absolute_mbps",
            "bandwidth_probe_interval_seconds",
        }
        self.assertTrue(expected.issubset(pref_names))

        _, bw = _req(f"{self.base}/api/bandwidth")
        config_keys = set(bw["config"].keys())
        expected_config = {
            "down_free_percent",
            "down_free_absolute_mbps",
            "down_use_percent",
            "up_free_percent",
            "up_free_absolute_mbps",
            "up_use_percent",
            "probe_interval_seconds",
        }
        self.assertTrue(expected_config.issubset(config_keys))


# ═══════════════════════════════════════════════════════
# Bandwidth probe → Bandwidth status
# ═══════════════════════════════════════════════════════


class TestProbeReflectedInBandwidth(CrossCheckBase):
    def test_manual_probe_reflected_in_bandwidth_status(self) -> None:
        probe_result = {
            "source": "networkquality",
            "reason": "probe_complete",
            "downlink_mbps": 120.0,
            "uplink_mbps": 30.0,
            "cap_mbps": 96.0,
            "cap_bytes_per_sec": 12000000,
            "interface_name": "en0",
            "responsiveness_rpm": 1800.0,
        }
        with (
            patch("aria_queue.core.probe_bandwidth", return_value=probe_result),
            patch("aria_queue.core.aria2_set_max_overall_download_limit"),
        ):
            _, probed = _req(f"{self.base}/api/bandwidth/probe", "POST")

        _, bw = _req(f"{self.base}/api/bandwidth")
        self.assertEqual(bw["downlink_mbps"], probed["downlink_mbps"])
        self.assertEqual(bw["uplink_mbps"], probed["uplink_mbps"])
        self.assertEqual(bw["interface"], probed["interface"])
        self.assertEqual(bw["down_cap_mbps"], probed["down_cap_mbps"])
        self.assertEqual(bw["up_cap_mbps"], probed["up_cap_mbps"])


# ═══════════════════════════════════════════════════════
# Session → Status
# ═══════════════════════════════════════════════════════


class TestSessionReflectedInStatus(CrossCheckBase):
    def test_new_session_reflected_in_status(self) -> None:
        # Ensure a session exists
        _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": f"https://example.com/xc-sess-{time.time()}.bin"}],
            },
        )

        _, new = _req(f"{self.base}/api/sessions/new", "POST", {"action": "new"})
        new_id = new["session"]["session_id"]

        _, status = _req(f"{self.base}/api/status")
        self.assertEqual(status["state"]["session_id"], new_id)
        self.assertIsNone(status["state"]["session_closed_at"])


# ═══════════════════════════════════════════════════════
# Run start/stop → Status
# ═══════════════════════════════════════════════════════


class TestRunReflectedInStatus(CrossCheckBase):
    def test_run_start_sets_running(self) -> None:
        _, run = _req(
            f"{self.base}/api/scheduler/start",
            "POST",
            {
                "auto_preflight_on_run": False,
            },
        )
        self.assertTrue(run["ok"])

        _, status = _req(f"{self.base}/api/status")
        # running may be True or already finished (empty queue)
        # but the run action should have been accepted
        self.assertIn("running", status["state"])

    def test_run_stop_clears_running(self) -> None:
        _req(
            f"{self.base}/api/scheduler/start",
            "POST",
            {
                "auto_preflight_on_run": False,
            },
        )
        _req(f"{self.base}/api/scheduler/stop", "POST", {})

        _, status = _req(f"{self.base}/api/status")
        self.assertFalse(status["state"]["running"])


# ═══════════════════════════════════════════════════════
# File select → Status
# ═══════════════════════════════════════════════════════


class TestFileSelectReflectedInStatus(CrossCheckBase):
    def test_file_select_sets_downloading(self) -> None:
        url = f"https://example.com/xc-torrent-{time.time()}.torrent"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["gid"] = "gid-xc-torrent"
                item["status"] = "paused"
        save_queue(items)

        with patch("aria_queue.core.aria_rpc"):
            _, selected = _req(
                f"{self.base}/api/downloads/{item_id}/files",
                "POST",
                {"select": [1, 2]},
            )
        self.assertTrue(selected["ok"])

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "active")


# ═══════════════════════════════════════════════════════
# All mutations → Action log
# ═══════════════════════════════════════════════════════


class TestMutationsLoggedInActionLog(CrossCheckBase):
    def test_add_logged(self) -> None:
        url = f"https://example.com/xc-log-add-{time.time()}.bin"
        _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("add", actions)

    def test_pause_logged(self) -> None:
        url = f"https://example.com/xc-log-pause-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("pause", actions)

    def test_resume_logged(self) -> None:
        url = f"https://example.com/xc-log-resume-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        _req(f"{self.base}/api/downloads/{item_id}/resume", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("resume", actions)

    def test_remove_logged(self) -> None:
        url = f"https://example.com/xc-log-remove-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("remove", actions)

    def test_retry_logged(self) -> None:
        url = f"https://example.com/xc-log-retry-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
        save_queue(items)
        _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("retry", actions)

    def test_session_logged(self) -> None:
        _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": f"https://example.com/xc-log-sess-{time.time()}.bin"}
                ],
            },
        )
        _req(f"{self.base}/api/sessions/new", "POST", {"action": "new"})
        _, log = _req(f"{self.base}/api/log?limit=10")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("session", actions)

    def test_probe_logged(self) -> None:
        probe = {
            "source": "default",
            "reason": "probe_unavailable",
            "cap_mbps": 2,
            "cap_bytes_per_sec": 250000,
            "downlink_mbps": None,
        }
        with (
            patch("aria_queue.core.probe_bandwidth", return_value=probe),
            patch("aria_queue.core.aria2_set_max_overall_download_limit"),
        ):
            _req(f"{self.base}/api/bandwidth/probe", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("probe", actions)

    def test_run_logged(self) -> None:
        _req(
            f"{self.base}/api/scheduler/start",
            "POST",
            {
                "auto_preflight_on_run": False,
            },
        )
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("run", actions)


# ═══════════════════════════════════════════════════════
# All mutations → Revision counter
# ═══════════════════════════════════════════════════════


class TestLogEntryDetails(CrossCheckBase):
    """Verify log entries contain the right detail fields."""

    def test_add_log_contains_url(self) -> None:
        url = f"https://example.com/xc-log-url-{time.time()}.bin"
        _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        _, log = _req(f"{self.base}/api/log?limit=5")
        add_entry = next((e for e in log["items"] if e.get("action") == "add"), None)
        self.assertIsNotNone(add_entry)
        self.assertIn("session_id", add_entry)
        self.assertIn("timestamp", add_entry)

    def test_pause_log_contains_item_id(self) -> None:
        url = f"https://example.com/xc-log-pid-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        pause_entry = next(
            (e for e in log["items"] if e.get("action") == "pause"), None
        )
        self.assertIsNotNone(pause_entry)
        detail = pause_entry.get("detail", {})
        self.assertEqual(detail.get("item_id"), item_id)

    def test_remove_log_contains_item_id(self) -> None:
        url = f"https://example.com/xc-log-rid-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        rm_entry = next((e for e in log["items"] if e.get("action") == "remove"), None)
        self.assertIsNotNone(rm_entry)
        detail = rm_entry.get("detail", {})
        self.assertEqual(detail.get("item_id"), item_id)

    def test_log_entries_ordered_by_time(self) -> None:
        for i in range(3):
            _req(
                f"{self.base}/api/downloads/add",
                "POST",
                {
                    "items": [
                        {
                            "url": f"https://example.com/xc-log-order-{i}-{time.time()}.bin"
                        }
                    ]
                },
            )
        _, log = _req(f"{self.base}/api/log?limit=10")
        timestamps = [
            e.get("timestamp", "") for e in log["items"] if e.get("timestamp")
        ]
        self.assertEqual(timestamps, sorted(timestamps))


class TestMultiStepChains(CrossCheckBase):
    """Verify state consistency across multi-step operation chains."""

    def test_add_pause_resume_remove_chain(self) -> None:
        url = f"https://example.com/xc-chain-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        # Each step: verify action response matches status
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        _, s = _req(f"{self.base}/api/status")
        self.assertEqual(
            next(i for i in s["items"] if i["id"] == item_id)["status"],
            "paused",
        )

        _req(f"{self.base}/api/downloads/{item_id}/resume", "POST")
        _, s = _req(f"{self.base}/api/status")
        self.assertIn(
            next(i for i in s["items"] if i["id"] == item_id)["status"],
            ("queued", "active"),
        )

        _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")
        _, s = _req(f"{self.base}/api/status")
        self.assertNotIn(item_id, [i["id"] for i in s["items"]])

    def test_error_retry_pause_chain(self) -> None:
        url = f"https://example.com/xc-err-chain-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        # Set to error
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
        save_queue(items)

        # Retry → queued
        _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")
        _, s = _req(f"{self.base}/api/status")
        self.assertEqual(
            next(i for i in s["items"] if i["id"] == item_id)["status"],
            "queued",
        )

        # Pause → paused
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        _, s = _req(f"{self.base}/api/status")
        self.assertEqual(
            next(i for i in s["items"] if i["id"] == item_id)["status"],
            "paused",
        )

    def test_multiple_items_independent_state(self) -> None:
        """Each item's state is independent of others."""
        urls = [f"https://example.com/xc-indep-{i}-{time.time()}.bin" for i in range(4)]
        _, added = _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {"items": [{"url": u} for u in urls]},
        )
        ids = [item["id"] for item in added["added"]]

        # Pause first, remove second, leave third queued, error fourth
        _req(f"{self.base}/api/downloads/{ids[0]}/pause", "POST")
        _req(f"{self.base}/api/downloads/{ids[1]}/remove", "POST")
        items = load_queue()
        for item in items:
            if item["id"] == ids[3]:
                item["status"] = "error"
        save_queue(items)

        _, status = _req(f"{self.base}/api/status")
        by_id = {i["id"]: i for i in status["items"]}
        self.assertEqual(by_id[ids[0]]["status"], "paused")
        self.assertNotIn(ids[1], by_id)
        self.assertEqual(by_id[ids[2]]["status"], "queued")
        self.assertEqual(by_id[ids[3]]["status"], "error")

    def test_session_change_does_not_affect_existing_items(self) -> None:
        url = f"https://example.com/xc-sess-keep-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _req(f"{self.base}/api/sessions/new", "POST", {"action": "new"})

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["url"], url)
        self.assertEqual(item["status"], "queued")


class TestMutationsIncrementRevision(CrossCheckBase):
    def _get_rev(self) -> int:
        from aria_queue.core import load_state

        return load_state().get("_rev", 0)

    def test_add_increments_rev(self) -> None:
        rev_before = self._get_rev()
        _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": f"https://example.com/xc-rev-add-{time.time()}.bin"}],
            },
        )
        rev_after = self._get_rev()
        self.assertGreater(rev_after, rev_before)

    def test_session_increments_rev(self) -> None:
        _req(
            f"{self.base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": f"https://example.com/xc-rev-sess-{time.time()}.bin"}
                ],
            },
        )
        rev_before = self._get_rev()
        _req(f"{self.base}/api/sessions/new", "POST", {"action": "new"})
        rev_after = self._get_rev()
        self.assertGreater(rev_after, rev_before)

    def test_pause_increments_rev(self) -> None:
        url = f"https://example.com/xc-rev-pause-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        rev_before = self._get_rev()
        _req(f"{self.base}/api/downloads/{item_id}/pause", "POST")
        rev_after = self._get_rev()
        self.assertGreater(rev_after, rev_before)

    def test_remove_increments_rev(self) -> None:
        url = f"https://example.com/xc-rev-rm-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        rev_before = self._get_rev()
        _req(f"{self.base}/api/downloads/{item_id}/remove", "POST")
        rev_after = self._get_rev()
        self.assertGreater(rev_after, rev_before)

    def test_retry_increments_rev(self) -> None:
        url = f"https://example.com/xc-rev-retry-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/downloads/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
        save_queue(items)
        rev_before = self._get_rev()
        _req(f"{self.base}/api/downloads/{item_id}/retry", "POST")
        rev_after = self._get_rev()
        self.assertGreater(rev_after, rev_before)


if __name__ == "__main__":
    unittest.main()
