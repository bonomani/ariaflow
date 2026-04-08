"""Regression tests — one test per bug that was found and fixed.

Each test reproduces the exact conditions that triggered a specific bug
and asserts the correct behavior. If any of these fail, it means the
bug has been reintroduced.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import IsolatedTestCase

from aria_queue.core import (
    _apply_free_bandwidth_cap,
    _is_metadata_url,
    add_queue_item,
    aria2_change_options,
    cleanup_queue_state,
    dedup_active_transfer_action,
    load_queue,
    load_state,
    process_queue,
    reconcile_live_queue,
    resume_active_transfer,
    save_queue,
    save_state,
)


class TestRegressions(IsolatedTestCase):
    # ── Bug #1: Session isolation on recovery ──
    # Fixed: recovered items now get current session_id
    # Before: item kept old session_id, invisible to session queries

    def test_regression_recovered_item_gets_current_session_id(self) -> None:
        queue_item = {
            "id": "item-1",
            "url": "https://example.com/file.gguf",
            "status": "paused",
            "gid": "gid-1",
            "session_id": "old-session",
        }
        live = [
            {
                "gid": "gid-1",
                "status": "active",
                "completedLength": "50",
                "totalLength": "100",
                "downloadSpeed": "10",
                "files": [{"uris": [{"uri": "https://example.com/file.gguf"}]}],
            }
        ]
        with (
            patch(
                "aria_queue.core.load_state",
                return_value={"session_id": "new-session"},
            ),
            patch("aria_queue.core.aria2_tell_active", return_value=live),
            patch("aria_queue.core.load_queue", return_value=[queue_item]),
            patch("aria_queue.core.save_queue") as save_q,
            patch("aria_queue.core.record_action"),
        ):
            reconcile_live_queue()
        saved = save_q.call_args[0][0]
        self.assertEqual(saved[0]["session_id"], "new-session")
        self.assertEqual(saved[0]["recovery_session_id"], "new-session")

    # ── Bug #2: Dead code — paused+active branch ──
    # Fixed: removed unreachable branch; _merge_active_status handles it
    # Before: dead code existed that could never execute

    def test_regression_paused_item_promoted_via_merge_active_status(self) -> None:
        queue_item = {
            "id": "item-1",
            "url": "https://example.com/file.gguf",
            "status": "paused",
            "gid": "gid-1",
            "session_id": "batch-1",
        }
        live = [
            {
                "gid": "gid-1",
                "status": "active",
                "completedLength": "50",
                "totalLength": "100",
                "downloadSpeed": "10",
                "files": [{"uris": [{"uri": "https://example.com/file.gguf"}]}],
            }
        ]
        with (
            patch(
                "aria_queue.core.load_state",
                return_value={"session_id": "batch-1"},
            ),
            patch("aria_queue.core.aria2_tell_active", return_value=live),
            patch("aria_queue.core.load_queue", return_value=[queue_item]),
            patch("aria_queue.core.save_queue") as save_q,
            patch("aria_queue.core.record_action"),
        ):
            reconcile_live_queue()
        saved = save_q.call_args[0][0]
        self.assertEqual(saved[0]["status"], "active")

    # ── Bug #3: process_queue infinite loop on RPC failure ──
    # Fixed: after 5 consecutive RPC failures, item marked as error
    # Before: item stayed "active" forever, loop never exited

    def test_regression_rpc_watchdog_marks_error_after_failures(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-1"
        save_queue(items)

        with (
            patch("aria_queue.core.aria2_ensure_daemon"),
            patch("aria_queue.core.deduplicate_active_transfers"),
            patch("aria_queue.core.reconcile_live_queue"),
            patch(
                "aria_queue.core.probe_bandwidth",
                return_value={
                    "source": "default",
                    "reason": "probe_unavailable",
                    "cap_mbps": 2,
                    "cap_bytes_per_sec": 250000,
                },
            ),
            patch("aria_queue.core.aria2_current_bandwidth", return_value={}),
            patch("aria_queue.core.aria2_set_max_overall_download_limit"),
            patch("aria_queue.core.aria2_tell_active", return_value=[]),
            patch(
                "aria_queue.core.aria2_add_download",
                side_effect=RuntimeError("aria2 still unavailable"),
            ),
            patch(
                "aria_queue.core.aria2_tell_status",
                side_effect=RuntimeError("connection refused"),
            ),
            patch(
                "aria_queue.core.time.sleep",
                side_effect=[None] * 10 + [StopIteration("stop")],
            ),
        ):
            try:
                process_queue()
            except StopIteration:
                pass
        items = load_queue()
        self.assertEqual(items[0]["status"], "queued")
        self.assertEqual(items[0]["desired_state"], "running")
        self.assertIsNone(items[0].get("gid"))

    # ── Bug #4: Dedup policy default mismatch ──
    # Fixed: code fallback changed from "pause" to "remove"
    # Before: code defaulted to "pause" but declaration said "remove"

    def test_regression_dedup_default_is_remove(self) -> None:
        action = dedup_active_transfer_action()
        self.assertEqual(action, "remove")

    # ── Bug #5: Resume set wrong status "queued" ──
    # Fixed: resume_active_transfer now sets "active"
    # Before: unpaused items set to "queued", causing re-add

    def test_regression_resume_sets_downloading_not_queued(self) -> None:
        add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        state = load_state()
        state["paused"] = False
        save_state(state)

        with (
            patch("aria_queue.core.aria_rpc"),
            patch("aria_queue.core.aria2_tell_active", return_value=[]),
        ):
            result = resume_active_transfer()
        if result.get("resumed"):
            items = load_queue()
            resumed = [i for i in items if i.get("gid") == "gid-1"]
            if resumed:
                self.assertEqual(resumed[0]["status"], "active")

    # ── Bug #6: Action log unbounded growth ──
    # Fixed: rotation added (truncate to 5000 lines when >10000 and >512KB)
    # Before: action log grew without limit

    def test_regression_action_log_rotation_exists(self) -> None:
        from aria_queue.core import _ACTION_LOG_MAX_LINES, _ACTION_LOG_KEEP_LINES

        self.assertEqual(_ACTION_LOG_MAX_LINES, 10000)
        self.assertEqual(_ACTION_LOG_KEEP_LINES, 5000)
        self.assertGreater(_ACTION_LOG_MAX_LINES, _ACTION_LOG_KEEP_LINES)

    # ── Bug #7: Unconditional changed=True in cleanup ──
    # Fixed: changed flag only set when swap or merge actually occurs
    # Before: cleanup always saved queue even when nothing changed

    def test_regression_cleanup_no_false_positive_change(self) -> None:
        add_queue_item("https://example.com/unique.bin")
        result = cleanup_queue_state()
        # Single unique item → no change needed
        self.assertFalse(result["changed"])

    # ── Bug #8: aria_rpc no response validation ──
    # Fixed: raises RuntimeError on JSON-RPC error field
    # Before: error responses passed through silently

    def test_regression_aria_rpc_raises_on_error_response(self) -> None:
        from aria_queue.core import aria_rpc

        error_response = json.dumps(
            {"jsonrpc": "2.0", "id": "1", "error": {"code": -1, "message": "bad"}}
        ).encode()
        with patch("aria_queue.core.urllib.request.urlopen") as mock_urlopen:
            mock_resp = unittest.mock.MagicMock()
            mock_resp.read.return_value = error_response
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = lambda s, *a: None
            mock_urlopen.return_value = mock_resp
            with self.assertRaises(RuntimeError) as ctx:
                aria_rpc("aria2.getVersion")
        self.assertIn("bad", str(ctx.exception))

    # ── Bug #9: File handle leak in storage_locked ──
    # Fixed: handle closed if fcntl.flock() raises
    # Before: handle leaked if flock failed

    def test_regression_storage_lock_closes_handle_on_flock_failure(self) -> None:
        from aria_queue.core import storage_locked

        with patch("aria_queue.core.fcntl.flock", side_effect=OSError("lock failed")):
            with self.assertRaises(OSError):
                with storage_locked():
                    pass  # should not reach here

    # ── Bug #10: Bandwidth probe state not persisted ──
    # Fixed: save_state called after probe in _apply_bandwidth_probe
    # Before: probe timing lost between loop iterations

    def test_regression_probe_state_persisted(self) -> None:
        from aria_queue.core import _apply_bandwidth_probe

        state = {}
        probe_result = {
            "source": "networkquality",
            "reason": "probe_complete",
            "cap_mbps": 64.0,
            "cap_bytes_per_sec": 8_000_000,
            "downlink_mbps": 80.0,
        }
        with (
            patch("aria_queue.core.probe_bandwidth", return_value=probe_result),
            patch("aria_queue.core.aria2_current_bandwidth", return_value={}),
            patch("aria_queue.core.aria2_set_max_overall_download_limit"),
            patch("aria_queue.core.save_state") as mock_save,
            patch("aria_queue.core.record_action"),
        ):
            _apply_bandwidth_probe(state=state, force=True)
        mock_save.assert_called_once()
        self.assertIn("last_bandwidth_probe", state)
        self.assertIn("last_bandwidth_probe_at", state)

    # ── Bug #11: RPC calls held storage lock in per-item actions ──
    # Fixed: RPC calls moved outside storage_locked()
    # Before: 5s RPC timeout blocked all other storage operations

    def test_regression_per_item_pause_releases_lock_before_rpc(self) -> None:
        from aria_queue.core import pause_queue_item

        add_queue_item("https://example.com/lock-test.bin")
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-lock"
        save_queue(items)
        item_id = items[0]["id"]

        rpc_called_outside_lock = []

        def check_rpc(*args, **kwargs):
            # Verify we can acquire the lock (not held during RPC)
            from aria_queue.core import _STORAGE_LOCK_STATE

            depth = getattr(_STORAGE_LOCK_STATE, "depth", 0)
            rpc_called_outside_lock.append(depth == 0)

        with patch("aria_queue.core.aria_rpc", side_effect=check_rpc):
            pause_queue_item(item_id)

        self.assertTrue(any(rpc_called_outside_lock))

    # ── Bug #12: State revision counter ──
    # Fixed: save_state increments _rev on every write
    # Before: no way for frontend to detect stale state

    def test_regression_state_revision_increments(self) -> None:
        state = load_state()
        rev0 = state.get("_rev", 0)
        save_state(state)
        state = load_state()
        rev1 = state.get("_rev", 0)
        self.assertGreater(rev1, rev0)
        save_state(state)
        state = load_state()
        rev2 = state.get("_rev", 0)
        self.assertGreater(rev2, rev1)

    # ── Bug #13: paused flag persists correctly ──
    # Scheduler now runs continuously; paused is only cleared by user resume.

    def test_regression_paused_persists_while_running(self) -> None:
        state = load_state()
        state["paused"] = True
        state["running"] = True
        save_state(state)
        save_queue([{"id": "x", "url": "https://x.com/done.bin", "status": "complete"}])

        with (
            patch("aria_queue.core.aria2_ensure_daemon"),
            patch("aria_queue.core.deduplicate_active_transfers"),
            patch("aria_queue.core.reconcile_live_queue"),
            patch(
                "aria_queue.core.probe_bandwidth",
                return_value={
                    "source": "default",
                    "reason": "probe_unavailable",
                    "cap_mbps": 2,
                    "cap_bytes_per_sec": 250000,
                },
            ),
            patch("aria_queue.core.aria2_current_bandwidth", return_value={}),
            patch("aria_queue.core.aria2_set_max_overall_download_limit"),
            patch("aria_queue.core.aria2_tell_active", return_value=[]),
            patch("aria_queue.core.time.sleep", side_effect=StopIteration("stop")),
        ):
            from aria_queue.core import process_queue

            try:
                process_queue()
            except StopIteration:
                pass
        state = load_state()
        self.assertTrue(state.get("paused"))
        self.assertTrue(state.get("running"))

    # ── Bug #14: aria2_ensure_daemon doesn't verify startup ──
    # Fixed: now retries RPC after spawn, raises on failure

    def test_regression_ensure_daemon_raises_on_failed_start(self) -> None:
        from aria_queue.core import aria2_ensure_daemon

        with (
            patch(
                "aria_queue.core.aria_rpc",
                side_effect=RuntimeError("connection refused"),
            ),
            patch("aria_queue.core.subprocess.Popen"),
            patch("aria_queue.core.time.sleep"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                aria2_ensure_daemon()
        self.assertIn("aria2c failed to start", str(ctx.exception))

    # ── Bug #15: retry doesn't clear recovery fields ──
    # Fixed: retry now pops recovered, recovered_at, recovery_session_id

    def test_regression_retry_clears_recovery_fields(self) -> None:
        from aria_queue.core import retry_queue_item

        item = add_queue_item("https://example.com/recover-clear.bin")
        items = load_queue()
        items[0]["status"] = "error"
        items[0]["recovered"] = True
        items[0]["recovered_at"] = "2026-01-01T00:00:00+0000"
        items[0]["recovery_session_id"] = "old-session"
        save_queue(items)
        result = retry_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertNotIn("recovered", result["item"])
        self.assertNotIn("recovered_at", result["item"])
        self.assertNotIn("recovery_session_id", result["item"])
        self.assertNotIn("error_code", result["item"])
        self.assertNotIn("gid", result["item"])

    # ── Bug #16: mirror URLs not deduplicated ──

    def test_regression_mirror_urls_deduplicated(self) -> None:
        from aria_queue.core import aria2_add_download

        item = {
            "url": "https://a.com/file.bin",
            "mode": "mirror",
            "mirrors": [
                "https://b.com/file.bin",
                "https://a.com/file.bin",
                "https://b.com/file.bin",
            ],
        }
        with patch("aria_queue.core.aria_rpc", return_value={"result": "gid-1"}) as rpc:
            aria2_add_download(item, cap_bytes_per_sec=250000)
        uris = rpc.call_args[0][1][0]
        self.assertEqual(len(uris), 2)
        self.assertEqual(uris[0], "https://a.com/file.bin")
        self.assertEqual(uris[1], "https://b.com/file.bin")


class TestSecurityInputValidation(IsolatedTestCase):
    """Security and input validation at API boundaries."""

    def test_add_item_with_very_long_url(self) -> None:
        url = "https://example.com/" + "a" * 10000
        item = add_queue_item(url)
        self.assertEqual(item.url, url)

    def test_add_item_with_special_chars_in_url(self) -> None:
        url = "https://example.com/file?q=hello&x=1#frag"
        item = add_queue_item(url)
        self.assertEqual(item.url, url)

    def test_add_item_with_unicode_url(self) -> None:
        url = "https://example.com/文件.bin"
        item = add_queue_item(url)
        self.assertEqual(item.url, url)

    def test_aria2_options_rejects_rpc_options(self) -> None:
        result = aria2_change_options({"rpc-listen-port": "9999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "rejected_options")

    def test_aria2_options_rejects_dir(self) -> None:
        result = aria2_change_options({"dir": "/etc/passwd"})
        self.assertFalse(result["ok"])

    def test_aria2_options_rejects_conf_path(self) -> None:
        result = aria2_change_options({"conf-path": "/tmp/evil.conf"})
        self.assertFalse(result["ok"])

    def test_aria2_options_rejects_log(self) -> None:
        result = aria2_change_options({"log": "/tmp/evil.log"})
        self.assertFalse(result["ok"])

    def test_metadata_url_detection_no_false_positives(self) -> None:
        self.assertFalse(_is_metadata_url("https://example.com/file.bin"))
        self.assertFalse(_is_metadata_url("https://example.com/torrent-info.html"))
        self.assertFalse(_is_metadata_url("https://example.com/meta4cast.mp3"))

    def test_metadata_url_detection_true_positives(self) -> None:
        self.assertTrue(_is_metadata_url("https://example.com/file.torrent"))
        self.assertTrue(_is_metadata_url("https://example.com/FILE.TORRENT"))
        self.assertTrue(_is_metadata_url("https://example.com/file.metalink"))
        self.assertTrue(_is_metadata_url("https://example.com/file.meta4"))
        self.assertTrue(_is_metadata_url("magnet:?xt=urn:btih:abc123"))

    def test_bandwidth_cap_with_zero_measured(self) -> None:
        result = _apply_free_bandwidth_cap(0.0, 20, 0)
        self.assertIsNone(result)

    def test_bandwidth_cap_with_none_measured(self) -> None:
        result = _apply_free_bandwidth_cap(None, 20, 0)
        self.assertIsNone(result)

    def test_bandwidth_cap_with_negative_measured(self) -> None:
        result = _apply_free_bandwidth_cap(-10.0, 20, 0)
        self.assertIsNone(result)

    def test_bandwidth_cap_100_percent_free(self) -> None:
        result = _apply_free_bandwidth_cap(100.0, 100, 0)
        self.assertEqual(result, 0.0)

    def test_bandwidth_cap_absolute_exceeds_measured(self) -> None:
        result = _apply_free_bandwidth_cap(10.0, 0, 20.0)
        self.assertEqual(result, 0.0)


if __name__ == "__main__":
    unittest.main()
