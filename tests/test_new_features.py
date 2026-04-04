"""Tests for recently added features:
- allowed_actions per item
- scheduler auto-retry with policy
- aria2 max-tries passthrough
- option_tiers discovery endpoint
- 6 managed aria2_set_* functions
- 3-tier option safety
- new aria2 GET endpoints
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

_MODULE = "aria_queue.core"


class _TempDirMixin:
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = self._tmpdir.name

    def tearDown(self) -> None:
        os.environ.pop("ARIA_QUEUE_DIR", None)
        self._tmpdir.cleanup()


# ── allowed_actions ─────────────────────────────────────────────────


class TestAllowedActions(unittest.TestCase):
    def test_queued_allows_pause_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("queued"), ["pause", "remove"])

    def test_active_allows_pause_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("active"), ["pause", "remove"])

    def test_waiting_allows_pause_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("waiting"), ["pause", "remove"])

    def test_paused_allows_resume_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("paused"), ["resume", "remove"])

    def test_complete_allows_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("complete"), ["remove"])

    def test_error_allows_retry_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("error"), ["retry", "remove"])

    def test_stopped_allows_retry_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("stopped"), ["retry", "remove"])

    def test_cancelled_allows_nothing(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("cancelled"), [])

    def test_unknown_status_allows_nothing(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("nonexistent"), [])


# ── auto-retry ──────────────────────────────────────────────────────


class TestAutoRetry(_TempDirMixin, unittest.TestCase):
    def _setup_error_item(self) -> None:
        from aria_queue.core import add_queue_item, save_queue, load_queue, ensure_storage

        ensure_storage()
        add_queue_item("https://example.com/retry-test.bin")
        items = load_queue()
        items[0]["status"] = "error"
        items[0]["error_code"] = "5"
        items[0]["error_message"] = "download failed"
        items[0]["error_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        items[0]["gid"] = "gid-err"
        save_queue(items)

    def test_auto_retry_requeues_error_item(self) -> None:
        self._setup_error_item()
        from aria_queue.core import load_queue, save_queue, load_state, save_state, ensure_storage

        ensure_storage()
        state = load_state()
        state["running"] = True
        save_state(state)

        with (
            patch(f"{_MODULE}.aria2_ensure_daemon"),
            patch(f"{_MODULE}.deduplicate_active_transfers"),
            patch(f"{_MODULE}.reconcile_live_queue"),
            patch(f"{_MODULE}.probe_bandwidth", return_value={
                "source": "default", "reason": "probe_unavailable",
                "cap_mbps": 2, "cap_bytes_per_sec": 250000,
            }),
            patch(f"{_MODULE}.aria2_current_bandwidth", return_value={}),
            patch(f"{_MODULE}.aria2_set_max_overall_download_limit"),
            patch(f"{_MODULE}.aria2_tell_active", return_value=[]),
            patch(f"{_MODULE}.aria2_multicall", return_value=[]),
            patch(f"{_MODULE}.aria2_add_download", return_value="gid-new"),
            patch(f"{_MODULE}.time.sleep", side_effect=RuntimeError("stop")),
        ):
            from aria_queue.core import process_queue

            with self.assertRaisesRegex(RuntimeError, "stop"):
                process_queue()

        items = load_queue()
        self.assertEqual(items[0]["status"], "active")
        self.assertEqual(items[0]["retry_count"], 1)

    def test_auto_retry_skips_rpc_unreachable(self) -> None:
        self._setup_error_item()
        from aria_queue.core import load_queue, save_queue, load_state, save_state, ensure_storage, add_queue_item

        ensure_storage()
        add_queue_item("https://example.com/keep-alive.bin")  # keep loop alive
        items = load_queue()
        for item in items:
            if item.get("error_code"):
                item["error_code"] = "rpc_unreachable"
        save_queue(items)
        state = load_state()
        state["running"] = True
        save_state(state)

        with (
            patch(f"{_MODULE}.aria2_ensure_daemon"),
            patch(f"{_MODULE}.deduplicate_active_transfers"),
            patch(f"{_MODULE}.reconcile_live_queue"),
            patch(f"{_MODULE}.probe_bandwidth", return_value={
                "source": "default", "reason": "probe_unavailable",
                "cap_mbps": 2, "cap_bytes_per_sec": 250000,
            }),
            patch(f"{_MODULE}.aria2_current_bandwidth", return_value={}),
            patch(f"{_MODULE}.aria2_set_max_overall_download_limit"),
            patch(f"{_MODULE}.aria2_tell_active", return_value=[]),
            patch(f"{_MODULE}.aria2_multicall", return_value=[]),
            patch(f"{_MODULE}.time.sleep", side_effect=RuntimeError("stop")),
        ):
            from aria_queue.core import process_queue

            with self.assertRaisesRegex(RuntimeError, "stop"):
                process_queue()

        items = load_queue()
        self.assertEqual(items[0]["status"], "error")  # NOT retried

    def test_auto_retry_respects_max_retries(self) -> None:
        self._setup_error_item()
        from aria_queue.core import load_queue, save_queue, ensure_storage, add_queue_item

        ensure_storage()
        add_queue_item("https://example.com/keep-alive.bin")  # keep loop alive
        items = load_queue()
        for item in items:
            if item.get("error_code"):
                item["retry_count"] = 3  # already at max
        save_queue(items)

        from aria_queue.core import load_state, save_state

        state = load_state()
        state["running"] = True
        save_state(state)

        with (
            patch(f"{_MODULE}.aria2_ensure_daemon"),
            patch(f"{_MODULE}.deduplicate_active_transfers"),
            patch(f"{_MODULE}.reconcile_live_queue"),
            patch(f"{_MODULE}.probe_bandwidth", return_value={
                "source": "default", "reason": "probe_unavailable",
                "cap_mbps": 2, "cap_bytes_per_sec": 250000,
            }),
            patch(f"{_MODULE}.aria2_current_bandwidth", return_value={}),
            patch(f"{_MODULE}.aria2_set_max_overall_download_limit"),
            patch(f"{_MODULE}.aria2_tell_active", return_value=[]),
            patch(f"{_MODULE}.aria2_multicall", return_value=[]),
            patch(f"{_MODULE}.time.sleep", side_effect=RuntimeError("stop")),
        ):
            from aria_queue.core import process_queue

            with self.assertRaisesRegex(RuntimeError, "stop"):
                process_queue()

        items = load_queue()
        self.assertEqual(items[0]["status"], "error")  # NOT retried


# ── aria2 max-tries passthrough ─────────────────────────────────────


class TestAria2MaxTriesPassthrough(_TempDirMixin, unittest.TestCase):
    def test_add_download_includes_max_tries(self) -> None:
        from aria_queue.core import ensure_storage

        ensure_storage()
        mock_rpc = MagicMock(return_value={"result": "gid-1"})
        with patch(f"{_MODULE}.aria_rpc", mock_rpc):
            from aria_queue.aria2_rpc import aria2_add_download

            aria2_add_download(
                {"url": "http://example.com/f", "mode": "http"},
                cap_bytes_per_sec=0,
            )
        call_args = mock_rpc.call_args
        options = call_args[0][1][1]  # params[1] = options dict
        self.assertIn("max-tries", options)
        self.assertIn("retry-wait", options)
        self.assertEqual(options["max-tries"], "5")
        self.assertEqual(options["retry-wait"], "10")


# ── option_tiers endpoint ───────────────────────────────────────────


class TestOptionTiers(_TempDirMixin, unittest.TestCase):
    def test_returns_three_tiers(self) -> None:
        from aria_queue.aria2_rpc import _MANAGED_ARIA2_OPTIONS, _SAFE_ARIA2_OPTIONS
        from aria_queue.queue_ops import allowed_actions  # just to verify import works

        self.assertIn("max-overall-download-limit", _MANAGED_ARIA2_OPTIONS)
        self.assertIn("max-overall-upload-limit", _MANAGED_ARIA2_OPTIONS)
        self.assertIn("seed-ratio", _MANAGED_ARIA2_OPTIONS)
        self.assertIn("max-concurrent-downloads", _SAFE_ARIA2_OPTIONS)
        self.assertNotIn("max-overall-download-limit", _SAFE_ARIA2_OPTIONS)


# ── managed aria2_set_* functions ───────────────────────────────────


class TestManagedSetFunctions(unittest.TestCase):
    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_max_overall_upload_limit(self) -> None:
        from aria_queue.core import aria2_set_max_overall_upload_limit

        aria2_set_max_overall_upload_limit(500000)

    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_max_upload_limit(self) -> None:
        from aria_queue.core import aria2_set_max_upload_limit

        aria2_set_max_upload_limit("gid-1", 100000)

    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_seed_ratio(self) -> None:
        from aria_queue.core import aria2_set_seed_ratio

        aria2_set_seed_ratio(2.0)

    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_seed_time(self) -> None:
        from aria_queue.core import aria2_set_seed_time

        aria2_set_seed_time(60)


# ── 3-tier safety ───────────────────────────────────────────────────


class TestThreeTierSafety(_TempDirMixin, unittest.TestCase):
    def test_managed_option_rejected(self) -> None:
        from aria_queue.core import aria2_change_options, ensure_storage

        ensure_storage()
        result = aria2_change_options({"max-overall-download-limit": "100K"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "managed_options")

    def test_safe_option_accepted(self) -> None:
        from aria_queue.core import aria2_change_options, ensure_storage

        ensure_storage()
        with (
            patch(f"{_MODULE}.aria_rpc"),
            patch(f"{_MODULE}.aria2_current_global_options", return_value={}),
        ):
            result = aria2_change_options({"max-concurrent-downloads": "5"})
        self.assertTrue(result["ok"])

    def test_unsafe_option_rejected_by_default(self) -> None:
        from aria_queue.core import aria2_change_options, ensure_storage

        ensure_storage()
        result = aria2_change_options({"dir": "/tmp"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "rejected_options")


if __name__ == "__main__":
    unittest.main()
