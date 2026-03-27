from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aria_queue.contracts import load_declaration, save_declaration
from aria_queue.core import add_queue_item, cleanup_queue_state, load_queue, load_state, process_queue, save_queue, save_state


class QueueSchedulerTests(unittest.TestCase):
    """Focused tests for queue scheduling and runner-state transitions."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _set_simultaneous_limit(self, limit: int) -> None:
        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        for pref in prefs:
            if pref.get("name") == "max_simultaneous_downloads":
                pref["value"] = limit
                pref["options"] = [limit]
                break
        save_declaration(declaration)

    def test_process_queue_starts_only_one_download_with_default_sequential_limit(self) -> None:
        add_queue_item("https://example.com/one.gguf")
        add_queue_item("https://example.com/two.gguf")

        with patch("aria_queue.core.ensure_aria_daemon"), \
             patch("aria_queue.core.deduplicate_active_transfers"), \
             patch("aria_queue.core.reconcile_live_queue"), \
             patch("aria_queue.core.probe_bandwidth", return_value={"source": "default", "reason": "probe_unavailable", "cap_mbps": 2, "cap_bytes_per_sec": 250000}), \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth"), \
             patch("aria_queue.core.active_gids", return_value=[]), \
             patch("aria_queue.core.add_download", return_value="gid-1") as add_download, \
             patch("aria_queue.core.time.sleep", side_effect=RuntimeError("stop loop")):
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                process_queue()

        add_download.assert_called_once()

    def test_process_queue_respects_runner_paused_state_and_starts_no_new_downloads(self) -> None:
        add_queue_item("https://example.com/queued.gguf")
        state = load_state()
        state["paused"] = True
        save_state(state)

        with patch("aria_queue.core.ensure_aria_daemon"), \
             patch("aria_queue.core.deduplicate_active_transfers"), \
             patch("aria_queue.core.reconcile_live_queue"), \
             patch("aria_queue.core.probe_bandwidth", return_value={"source": "default", "reason": "probe_unavailable", "cap_mbps": 2, "cap_bytes_per_sec": 250000}), \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth"), \
             patch("aria_queue.core.active_gids", return_value=[]), \
             patch("aria_queue.core.add_download") as add_download, \
             patch("aria_queue.core.time.sleep", side_effect=RuntimeError("stop loop")):
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                process_queue()

        add_download.assert_not_called()
        self.assertEqual(load_state()["paused"], True)

    def test_process_queue_honors_active_slot_limit_before_starting_new_work(self) -> None:
        add_queue_item("https://example.com/already-running.gguf")
        add_queue_item("https://example.com/queued.gguf")
        self._set_simultaneous_limit(1)
        items = load_queue()
        items[0]["gid"] = "gid-running"
        items[0]["status"] = "downloading"
        items[0]["live_status"] = "active"
        save_queue(items)

        active_info = {
            "gid": "gid-running",
            "status": "active",
            "errorCode": "0",
            "errorMessage": "",
            "downloadSpeed": "5",
            "completedLength": "25",
            "totalLength": "100",
            "files": [{"uris": [{"uri": "https://example.com/already-running.gguf"}]}],
        }

        with patch("aria_queue.core.ensure_aria_daemon"), \
             patch("aria_queue.core.deduplicate_active_transfers"), \
             patch("aria_queue.core.reconcile_live_queue"), \
             patch("aria_queue.core.probe_bandwidth", return_value={"source": "default", "reason": "probe_unavailable", "cap_mbps": 2, "cap_bytes_per_sec": 250000}), \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth"), \
             patch("aria_queue.core.active_gids", return_value=[]), \
             patch("aria_queue.core.status", return_value=active_info), \
             patch("aria_queue.core.add_download", return_value="gid-new") as add_download, \
             patch("aria_queue.core.time.sleep", side_effect=RuntimeError("stop loop")):
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                process_queue()

        add_download.assert_not_called()

    def test_cleanup_queue_state_collapses_duplicate_nonterminal_rows(self) -> None:
        save_queue(
            [
                {
                    "id": "older",
                    "url": "https://example.com/model.gguf",
                    "status": "paused",
                    "gid": "gid-1",
                    "completedLength": "10",
                    "created_at": "2026-03-26T21:18:26+0100",
                },
                {
                    "id": "newer",
                    "url": "https://example.com/model.gguf",
                    "status": "paused",
                    "gid": "gid-1",
                    "completedLength": "20",
                    "recovered": True,
                    "recovered_at": "2026-03-26T21:19:42+0100",
                    "created_at": "2026-03-26T21:19:42+0100",
                },
            ]
        )

        result = cleanup_queue_state()

        self.assertTrue(result["changed"])
        items = load_queue()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["gid"], "gid-1")
        self.assertEqual(items[0]["completedLength"], "20")
        self.assertTrue(items[0].get("recovered"))

    def test_cleanup_queue_state_collapses_duplicate_error_rows(self) -> None:
        save_queue(
            [
                {
                    "id": "older-error",
                    "url": "https://releases.ubuntu.com/24.04/ubuntu-24.04.2-live-server-amd64.iso",
                    "status": "error",
                    "gid": "gid-error",
                    "error_message": "Resource not found",
                    "recovered": True,
                    "recovered_at": "2026-03-21T18:46:52+0100",
                    "recovery_session_id": "batch-old",
                    "created_at": "2026-03-21T18:46:52+0100",
                },
                {
                    "id": "newer-error",
                    "url": "https://releases.ubuntu.com/24.04/ubuntu-24.04.2-live-server-amd64.iso",
                    "status": "error",
                    "gid": "gid-error",
                    "error_message": "Resource not found",
                    "recovered_at": "2026-03-26T21:16:09+0100",
                    "recovery_session_id": "batch-new",
                    "created_at": "2026-03-26T21:16:09+0100",
                },
            ]
        )

        result = cleanup_queue_state()

        self.assertTrue(result["changed"])
        items = load_queue()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["gid"], "gid-error")
        self.assertEqual(items[0]["error_message"], "Resource not found")
        self.assertNotIn("recovered", items[0])
        self.assertNotIn("recovered_at", items[0])
        self.assertNotIn("recovery_session_id", items[0])

    def test_cleanup_queue_state_normalizes_stale_live_status_for_paused_item(self) -> None:
        save_queue(
            [
                {
                    "id": "paused-item",
                    "url": "https://example.com/model.gguf",
                    "status": "paused",
                    "gid": "gid-1",
                    "live_status": "active",
                    "created_at": "2026-03-27T10:00:00+0100",
                }
            ]
        )

        result = cleanup_queue_state()

        self.assertTrue(result["changed"])
        self.assertEqual(result["normalized"], 1)
        items = load_queue()
        self.assertEqual(items[0]["status"], "paused")
        self.assertEqual(items[0]["live_status"], "paused")

    def test_process_queue_runs_startup_cleanup_before_reconcile(self) -> None:
        save_queue(
            [
                {
                    "id": "older",
                    "url": "https://example.com/model.gguf",
                    "status": "paused",
                    "gid": "gid-1",
                    "completedLength": "10",
                },
                {
                    "id": "newer",
                    "url": "https://example.com/model.gguf",
                    "status": "paused",
                    "gid": "gid-1",
                    "completedLength": "20",
                    "recovered": True,
                },
            ]
        )

        with patch("aria_queue.core.ensure_aria_daemon"), \
             patch("aria_queue.core.deduplicate_active_transfers"), \
             patch("aria_queue.core.reconcile_live_queue"), \
             patch("aria_queue.core.probe_bandwidth", return_value={"source": "default", "reason": "probe_unavailable", "cap_mbps": 2, "cap_bytes_per_sec": 250000}), \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth"), \
             patch("aria_queue.core.active_gids", return_value=[]), \
             patch("aria_queue.core.add_download", return_value="gid-1"), \
             patch("aria_queue.core.time.sleep", side_effect=RuntimeError("stop loop")):
            with self.assertRaisesRegex(RuntimeError, "stop loop"):
                process_queue()

        items = load_queue()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["completedLength"], "20")
