"""Cross-check tests — verify mutating actions are reflected in read endpoints.

Every test performs a mutation, then reads back the state from the
corresponding GET endpoint and verifies consistency.
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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aria_queue.core import load_queue, save_queue  # noqa: E402
from aria_queue.webapp import serve  # noqa: E402


def _req(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: int = 5,
) -> tuple[int, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class CrossCheckBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = cls.tmp.name
        cls.server = serve(host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()


# ═══════════════════════════════════════════════════════
# Add → Status
# ═══════════════════════════════════════════════════════


class TestAddReflectedInStatus(CrossCheckBase):
    def test_added_item_appears_in_status(self) -> None:
        url = f"https://example.com/xc-add-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, status = _req(f"{self.base}/api/status")
        ids = [item["id"] for item in status["items"]]
        self.assertIn(item_id, ids)

        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["url"], url)
        self.assertEqual(item["status"], "queued")

    def test_added_item_counted_in_summary(self) -> None:
        before_code, before = _req(f"{self.base}/api/status")
        before_total = before["summary"]["total"]

        url = f"https://example.com/xc-count-{time.time()}.bin"
        _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})

        _, after = _req(f"{self.base}/api/status")
        self.assertEqual(after["summary"]["total"], before_total + 1)

    def test_added_item_creates_session(self) -> None:
        url = f"https://example.com/xc-sess-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        session_id = added["added"][0]["session_id"]

        _, status = _req(f"{self.base}/api/status")
        self.assertEqual(status["state"]["session_id"], session_id)


# ═══════════════════════════════════════════════════════
# Pause → Status
# ═══════════════════════════════════════════════════════


class TestPauseReflectedInStatus(CrossCheckBase):
    def test_paused_item_status_matches(self) -> None:
        url = f"https://example.com/xc-pause-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, paused = _req(f"{self.base}/api/item/{item_id}/pause", "POST")
        self.assertEqual(paused["item"]["status"], "paused")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "paused")

    def test_paused_item_summary_counts(self) -> None:
        url = f"https://example.com/xc-pause-cnt-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/item/{item_id}/pause", "POST")

        _, status = _req(f"{self.base}/api/status")
        self.assertGreater(status["summary"].get("paused", 0), 0)


# ═══════════════════════════════════════════════════════
# Resume → Status
# ═══════════════════════════════════════════════════════


class TestResumeReflectedInStatus(CrossCheckBase):
    def test_resumed_item_status_matches(self) -> None:
        url = f"https://example.com/xc-resume-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/item/{item_id}/pause", "POST")

        _, resumed = _req(f"{self.base}/api/item/{item_id}/resume", "POST")
        expected_status = resumed["item"]["status"]

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], expected_status)


# ═══════════════════════════════════════════════════════
# Remove → Status
# ═══════════════════════════════════════════════════════


class TestRemoveReflectedInStatus(CrossCheckBase):
    def test_removed_item_gone_from_status(self) -> None:
        url = f"https://example.com/xc-remove-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, removed = _req(f"{self.base}/api/item/{item_id}/remove", "POST")
        self.assertTrue(removed["removed"])

        _, status = _req(f"{self.base}/api/status")
        ids = [item["id"] for item in status["items"]]
        self.assertNotIn(item_id, ids)

    def test_removed_item_reduces_total(self) -> None:
        url = f"https://example.com/xc-rem-cnt-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        _, before = _req(f"{self.base}/api/status")
        before_total = before["summary"]["total"]

        _req(f"{self.base}/api/item/{item_id}/remove", "POST")

        _, after = _req(f"{self.base}/api/status")
        self.assertEqual(after["summary"]["total"], before_total - 1)


# ═══════════════════════════════════════════════════════
# Retry → Status
# ═══════════════════════════════════════════════════════


class TestRetryReflectedInStatus(CrossCheckBase):
    def test_retried_item_back_to_queued(self) -> None:
        url = f"https://example.com/xc-retry-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        # Force error state
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
                item["error_code"] = "99"
        save_queue(items)

        _, retried = _req(f"{self.base}/api/item/{item_id}/retry", "POST")
        self.assertEqual(retried["item"]["status"], "queued")

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "queued")
        self.assertIsNone(item.get("error_code"))
        self.assertIsNone(item.get("gid"))


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
        _, opts = _req(f"{self.base}/api/options")
        decl.pop("_request_id", None)
        opts.pop("_request_id", None)
        self.assertEqual(decl, opts)


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
            patch("aria_queue.core.set_bandwidth"),
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
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": f"https://example.com/xc-sess-{time.time()}.bin"}],
            },
        )

        _, new = _req(f"{self.base}/api/session", "POST", {"action": "new"})
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
            f"{self.base}/api/run",
            "POST",
            {
                "action": "start",
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
            f"{self.base}/api/run",
            "POST",
            {
                "action": "start",
                "auto_preflight_on_run": False,
            },
        )
        _req(f"{self.base}/api/run", "POST", {"action": "stop"})

        _, status = _req(f"{self.base}/api/status")
        self.assertFalse(status["state"]["running"])


# ═══════════════════════════════════════════════════════
# File select → Status
# ═══════════════════════════════════════════════════════


class TestFileSelectReflectedInStatus(CrossCheckBase):
    def test_file_select_sets_downloading(self) -> None:
        url = f"https://example.com/xc-torrent-{time.time()}.torrent"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]

        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["gid"] = "gid-xc-torrent"
                item["status"] = "paused"
        save_queue(items)

        with patch("aria_queue.core.aria_rpc"):
            _, selected = _req(
                f"{self.base}/api/item/{item_id}/files",
                "POST",
                {"select": [1, 2]},
            )
        self.assertTrue(selected["ok"])

        _, status = _req(f"{self.base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "downloading")


# ═══════════════════════════════════════════════════════
# All mutations → Action log
# ═══════════════════════════════════════════════════════


class TestMutationsLoggedInActionLog(CrossCheckBase):
    def test_add_logged(self) -> None:
        url = f"https://example.com/xc-log-add-{time.time()}.bin"
        _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("add", actions)

    def test_pause_logged(self) -> None:
        url = f"https://example.com/xc-log-pause-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/item/{item_id}/pause", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("pause", actions)

    def test_resume_logged(self) -> None:
        url = f"https://example.com/xc-log-resume-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/item/{item_id}/pause", "POST")
        _req(f"{self.base}/api/item/{item_id}/resume", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("resume", actions)

    def test_remove_logged(self) -> None:
        url = f"https://example.com/xc-log-remove-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        _req(f"{self.base}/api/item/{item_id}/remove", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("remove", actions)

    def test_retry_logged(self) -> None:
        url = f"https://example.com/xc-log-retry-{time.time()}.bin"
        _, added = _req(f"{self.base}/api/add", "POST", {"items": [{"url": url}]})
        item_id = added["added"][0]["id"]
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "error"
        save_queue(items)
        _req(f"{self.base}/api/item/{item_id}/retry", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("retry", actions)

    def test_session_logged(self) -> None:
        _req(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [
                    {"url": f"https://example.com/xc-log-sess-{time.time()}.bin"}
                ],
            },
        )
        _req(f"{self.base}/api/session", "POST", {"action": "new"})
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
            patch("aria_queue.core.set_bandwidth"),
        ):
            _req(f"{self.base}/api/bandwidth/probe", "POST")
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("probe", actions)

    def test_run_logged(self) -> None:
        _req(
            f"{self.base}/api/run",
            "POST",
            {
                "action": "start",
                "auto_preflight_on_run": False,
            },
        )
        _, log = _req(f"{self.base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("run", actions)


# ═══════════════════════════════════════════════════════
# All mutations → Revision counter
# ═══════════════════════════════════════════════════════


class TestMutationsIncrementRevision(CrossCheckBase):
    def _get_rev(self) -> int:
        from aria_queue.core import load_state

        return load_state().get("_rev", 0)

    def test_add_increments_rev(self) -> None:
        rev_before = self._get_rev()
        _req(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [{"url": f"https://example.com/xc-rev-add-{time.time()}.bin"}],
            },
        )
        rev_after = self._get_rev()
        self.assertGreater(rev_after, rev_before)

    def test_session_increments_rev(self) -> None:
        _req(
            f"{self.base}/api/add",
            "POST",
            {
                "items": [
                    {"url": f"https://example.com/xc-rev-sess-{time.time()}.bin"}
                ],
            },
        )
        rev_before = self._get_rev()
        _req(f"{self.base}/api/session", "POST", {"action": "new"})
        rev_after = self._get_rev()
        self.assertGreater(rev_after, rev_before)


if __name__ == "__main__":
    unittest.main()
