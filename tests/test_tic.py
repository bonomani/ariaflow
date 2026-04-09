from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import IsolatedTestCase

from ariaflow_server.contracts import preflight, run_ucc
from ariaflow_server.core import (
    _apply_bandwidth_probe,
    _should_probe_bandwidth,
    add_queue_item,
    deduplicate_active_transfers,
    discover_active_transfer,
    load_action_log,
    load_queue,
    load_state,
    probe_bandwidth,
    process_queue,
    reconcile_live_queue,
    save_queue,
    save_state,
    start_new_state_session,
)
from ariaflow_server.install import (
    install_all,
    networkquality_status,
    status_all,
    uninstall_all,
)


class TicAriaFlowTests(IsolatedTestCase):
    """
    Name: test_tic
    Intent: verify queue enqueueing, preflight reporting, and structured UCC output.
    Scope: ariaflow command layer
    Trace targets: UIC pre-flight, UCC execution, TIC reporting
    """

    def test_enqueue_creates_queue_item(self) -> None:
        item = add_queue_item("https://example.com/model.gguf")
        self.assertTrue(item.id)
        self.assertEqual(item.status, "queued")
        self.assertTrue(item.session_id)
        from ariaflow_server.core import load_state

        state = load_state()
        self.assertTrue(state.get("session_started_at"))
        self.assertTrue(state.get("session_last_seen_at"))
        log = load_action_log()
        add_entry = next(
            entry for entry in reversed(log) if entry.get("action") == "add"
        )
        self.assertIn("session_id", add_entry)
        self.assertIn("observed_before", add_entry)
        self.assertIn("observed_after", add_entry)

    def test_new_session_closes_previous_and_starts_fresh(self) -> None:
        first = add_queue_item("https://example.com/one.gguf")
        state_before = load_state()
        next_state = start_new_state_session()
        self.assertNotEqual(
            state_before.get("session_id"), next_state.get("session_id")
        )
        self.assertTrue(next_state.get("session_started_at"))
        self.assertIsNone(next_state.get("session_closed_at"))
        self.assertEqual(first.session_id, state_before.get("session_id"))

    def test_enqueue_reuses_duplicate_url(self) -> None:
        first = add_queue_item("https://example.com/model.gguf")
        second = add_queue_item("https://example.com/model.gguf")
        self.assertEqual(first.id, second.id)
        log = load_action_log()
        duplicate_entry = next(
            entry for entry in reversed(log) if entry.get("reason") == "duplicate_url"
        )
        self.assertEqual(duplicate_entry["outcome"], "unchanged")

    def test_preflight_emits_gate_results(self) -> None:
        with (
            patch(
                "ariaflow_server.contracts.aria_rpc",
                return_value={"result": {"version": "1.37.0"}},
            ),
            patch("ariaflow_server.contracts.aria2_ensure_daemon") as ensure,
        ):
            result = preflight()
        self.assertIn("gates", result)
        self.assertIn("status", result)
        self.assertIn(result["exit_code"], [0, 1])
        self.assertNotIn("action_log", result)
        self.assertFalse(ensure.called)

    def test_preflight_bootstraps_aria2_when_rpc_is_initially_unavailable(self) -> None:
        with (
            patch(
                "ariaflow_server.contracts.aria_rpc",
                side_effect=[
                    RuntimeError("offline"),
                    {"result": {"version": "1.37.0"}},
                ],
            ),
            patch("ariaflow_server.contracts.aria2_ensure_daemon") as ensure,
        ):
            result = preflight()
        gate = next(
            gate for gate in result["gates"] if gate["name"] == "aria2_available"
        )
        self.assertTrue(gate["satisfied"])
        ensure.assert_called_once_with(port=6800)

    def test_auto_preflight_default_is_disabled(self) -> None:
        from ariaflow_server.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        auto = next(
            (pref for pref in prefs if pref.get("name") == "auto_preflight_on_run"), {}
        )
        self.assertFalse(auto.get("value", True))

    def test_concurrency_default_is_sequential(self) -> None:
        from ariaflow_server.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        limit = next(
            (
                pref
                for pref in prefs
                if pref.get("name") == "max_simultaneous_downloads"
            ),
            {},
        )
        self.assertEqual(limit.get("value", 0), 1)

    def test_duplicate_active_transfer_default_is_remove(self) -> None:
        from ariaflow_server.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        dedup = next(
            (
                pref
                for pref in prefs
                if pref.get("name") == "duplicate_active_transfer_action"
            ),
            {},
        )
        self.assertEqual(dedup.get("value"), "remove")

    def test_probe_fallback_reports_reason(self) -> None:
        with patch("ariaflow_server.core._find_networkquality", return_value=None):
            result = probe_bandwidth()
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["reason"], "probe_unavailable")
        self.assertIn("cap_mbps", result)
        self.assertEqual(result["cap_bytes_per_sec"], 250000)

    def test_probe_uses_machine_readable_networkquality_output(self) -> None:
        output = json.dumps(
            {
                "dl_throughput": 80_000_000,
                "dl_responsiveness": 1200,
                "interface_name": "en0",
            }
        )
        with (
            patch(
                "ariaflow_server.core._find_networkquality",
                return_value="/usr/bin/networkQuality",
            ),
            patch(
                "ariaflow_server.core.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=output
                ),
            ) as run,
        ):
            result = probe_bandwidth()
        run.assert_called_once_with(
            ["/usr/bin/networkQuality", "-u", "-c", "-s", "-M", "8"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        self.assertEqual(result["source"], "networkquality")
        self.assertEqual(result["reason"], "probe_complete")
        self.assertEqual(result["downlink_mbps"], 80.0)
        self.assertEqual(result["cap_mbps"], 64.0)
        self.assertEqual(result["cap_bytes_per_sec"], 8000000)
        self.assertEqual(result["responsiveness_rpm"], 1200.0)
        self.assertEqual(result["interface_name"], "en0")

    def test_probe_timeout_without_parse_uses_default_floor(self) -> None:
        timeout = subprocess.TimeoutExpired(
            cmd=["/usr/bin/networkQuality", "-u", "-c", "-s", "-M", "8"],
            timeout=10,
            output="",
        )
        with (
            patch(
                "ariaflow_server.core._find_networkquality",
                return_value="/usr/bin/networkQuality",
            ),
            patch("ariaflow_server.core.subprocess.run", side_effect=timeout),
        ):
            result = probe_bandwidth()
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["reason"], "probe_timeout_no_parse")
        self.assertTrue(result["partial"])
        self.assertEqual(result["cap_bytes_per_sec"], 250000)

    def test_should_probe_bandwidth_uses_interval(self) -> None:
        self.assertTrue(_should_probe_bandwidth({}))
        self.assertFalse(
            _should_probe_bandwidth({"last_bandwidth_probe_at": 100.0}, now=200.0)
        )
        self.assertTrue(
            _should_probe_bandwidth({"last_bandwidth_probe_at": 100.0}, now=281.0)
        )

    def test_apply_bandwidth_probe_reuses_recent_probe(self) -> None:
        state = {
            "last_bandwidth_probe": {
                "source": "networkquality",
                "reason": "probe_complete",
                "cap_mbps": 64.0,
                "cap_bytes_per_sec": 8_000_000,
            },
            "last_bandwidth_probe_at": 100.0,
        }
        with (
            patch("ariaflow_server.core.time.time", return_value=120.0),
            patch("ariaflow_server.core.probe_bandwidth") as probe_bandwidth_mock,
            patch("ariaflow_server.core.aria2_current_bandwidth", return_value={}),
            patch(
                "ariaflow_server.core.aria2_set_max_overall_download_limit"
            ) as set_bandwidth_mock,
            patch("ariaflow_server.core.record_action") as record_action_mock,
        ):
            probe, cap_mbps, cap_bytes_per_sec = _apply_bandwidth_probe(state=state)
        self.assertFalse(probe_bandwidth_mock.called)
        self.assertFalse(set_bandwidth_mock.called)
        self.assertEqual(cap_mbps, 64.0)
        self.assertEqual(cap_bytes_per_sec, 8_000_000)
        self.assertEqual(probe["interval_seconds"], 180)
        self.assertFalse(record_action_mock.called)

    def test_apply_bandwidth_probe_refreshes_stale_probe(self) -> None:
        state = {"last_bandwidth_probe_at": 100.0}
        fresh_probe = {
            "source": "networkquality",
            "reason": "probe_complete",
            "cap_mbps": 32.0,
            "cap_bytes_per_sec": 4_000_000,
        }
        with (
            patch("ariaflow_server.core.time.time", return_value=400.0),
            patch(
                "ariaflow_server.core.probe_bandwidth", return_value=fresh_probe
            ) as probe_bandwidth_mock,
            patch("ariaflow_server.core.aria2_current_bandwidth", return_value={}),
            patch(
                "ariaflow_server.core.aria2_set_max_overall_download_limit"
            ) as set_bandwidth_mock,
            patch("ariaflow_server.core.record_action") as record_action_mock,
        ):
            probe, cap_mbps, cap_bytes_per_sec = _apply_bandwidth_probe(state=state)
        probe_bandwidth_mock.assert_called_once()
        set_bandwidth_mock.assert_called_once_with(4_000_000, port=6800)
        record_action_mock.assert_called_once()
        self.assertEqual(cap_mbps, 32.0)
        self.assertEqual(cap_bytes_per_sec, 4_000_000)
        self.assertEqual(probe["interval_seconds"], 180)
        self.assertEqual(state["last_bandwidth_probe_at"], 400.0)

    def test_discover_active_transfer_prefers_state_gid(self) -> None:
        with (
            patch(
                "ariaflow_server.core.load_state",
                return_value={
                    "active_gid": "gid-1",
                    "active_url": "https://example.com/a.gguf",
                },
            ),
            patch(
                "ariaflow_server.core.aria2_tell_status",
                return_value={
                    "status": "active",
                    "completedLength": "10",
                    "totalLength": "100",
                    "downloadSpeed": "5",
                },
            ),
        ):
            active = discover_active_transfer()
        self.assertEqual(active["gid"], "gid-1")
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["percent"], 10.0)

    def test_discover_active_transfer_recovers_url_from_queue(self) -> None:
        with (
            patch(
                "ariaflow_server.core.load_state",
                return_value={"active_gid": "gid-1", "active_url": None},
            ),
            patch(
                "ariaflow_server.core.load_queue",
                return_value=[
                    {
                        "id": "item-1",
                        "url": "https://example.com/recovered.gguf",
                        "status": "paused",
                        "gid": "gid-1",
                    }
                ],
            ),
            patch(
                "ariaflow_server.core.aria2_tell_status",
                return_value={
                    "status": "active",
                    "completedLength": "10",
                    "totalLength": "100",
                    "downloadSpeed": "5",
                },
            ),
        ):
            active = discover_active_transfer()
        self.assertEqual(active["gid"], "gid-1")
        self.assertEqual(active["url"], "https://example.com/recovered.gguf")

    def test_reconcile_promotes_paused_item_to_downloading_when_live_active(
        self,
    ) -> None:
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
            patch("ariaflow_server.core.load_state", return_value={"session_id": "batch-1"}),
            patch("ariaflow_server.core.aria2_tell_active", return_value=live),
            patch("ariaflow_server.core.load_queue", return_value=[queue_item]),
            patch("ariaflow_server.core.save_queue") as save_queue,
            patch("ariaflow_server.core.record_action"),
        ):
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        saved = save_queue.call_args[0][0]
        self.assertEqual(saved[0]["status"], "active")

    def test_reconcile_live_queue_adopts_unmatched_active_job(self) -> None:
        with (
            patch("ariaflow_server.core.load_state", return_value={"session_id": "batch-1"}),
            patch(
                "ariaflow_server.core.aria2_tell_active",
                return_value=[
                    {
                        "gid": "gid-9",
                        "status": "active",
                        "completedLength": "5",
                        "totalLength": "100",
                        "downloadSpeed": "10",
                        "files": [{"uris": [{"uri": "https://example.com/new.gguf"}]}],
                    }
                ],
            ),
            patch("ariaflow_server.core.load_queue", return_value=[]),
            patch("ariaflow_server.core.save_queue") as save_queue,
            patch("ariaflow_server.core.record_action") as record_action,
        ):
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        self.assertEqual(result["recovered"], 1)
        save_queue.assert_called_once()
        record_action.assert_called_once()

    def test_reconcile_live_queue_updates_old_session_item_in_place(self) -> None:
        with (
            patch("ariaflow_server.core.load_state", return_value={"session_id": "batch-2"}),
            patch(
                "ariaflow_server.core.aria2_tell_active",
                return_value=[
                    {
                        "gid": "gid-9",
                        "status": "active",
                        "completedLength": "50",
                        "totalLength": "100",
                        "downloadSpeed": "10",
                        "files": [{"uris": [{"uri": "https://example.com/file.gguf"}]}],
                    }
                ],
            ),
            patch(
                "ariaflow_server.core.load_queue",
                return_value=[
                    {
                        "id": "item-1",
                        "url": "https://example.com/file.gguf",
                        "status": "paused",
                        "gid": "gid-old",
                        "session_id": "batch-1",
                    }
                ],
            ),
            patch("ariaflow_server.core.save_queue") as save_queue,
            patch("ariaflow_server.core.record_action") as record_action,
        ):
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        self.assertEqual(result["recovered"], 1)
        saved_items = save_queue.call_args[0][0]
        self.assertEqual(saved_items[0]["session_id"], "batch-2")
        self.assertEqual(saved_items[0]["recovery_session_id"], "batch-2")
        record_action.assert_called_once()

    def test_reconcile_live_queue_collapses_duplicate_rows_for_same_live_download(
        self,
    ) -> None:
        queue_items = [
            {
                "id": "item-1",
                "url": "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso",
                "status": "paused",
                "gid": "gid-old",
                "session_id": "batch-1",
                "completedLength": "199400000",
            },
            {
                "id": "item-2",
                "url": "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso",
                "status": "active",
                "gid": "gid-9",
                "session_id": "batch-2",
                "completedLength": "230300000",
                "recovered": True,
            },
        ]
        live = [
            {
                "gid": "gid-9",
                "status": "active",
                "completedLength": "230300000",
                "totalLength": "3200000000",
                "downloadSpeed": "10",
                "files": [
                    {
                        "uris": [
                            {
                                "uri": "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso"
                            }
                        ]
                    }
                ],
            }
        ]
        saved_items: list[dict] = []

        def capture_save(items: list[dict]) -> None:
            saved_items[:] = items

        with (
            patch("ariaflow_server.core.load_state", return_value={"session_id": "batch-3"}),
            patch("ariaflow_server.core.aria2_tell_active", return_value=live),
            patch("ariaflow_server.core.load_queue", return_value=queue_items),
            patch("ariaflow_server.core.save_queue", side_effect=capture_save),
            patch("ariaflow_server.core.record_action") as record_action,
        ):
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(len(saved_items), 1)
        self.assertEqual(saved_items[0]["gid"], "gid-9")
        self.assertEqual(
            saved_items[0]["url"],
            "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso",
        )
        self.assertEqual(saved_items[0]["completedLength"], "230300000")
        self.assertTrue(saved_items[0]["recovered"])
        record_action.assert_called_once()

    def test_deduplicate_active_transfers_removes_less_advanced_duplicates_by_default(
        self,
    ) -> None:
        active = [
            {
                "gid": "gid-keep",
                "status": "active",
                "completedLength": "30",
                "totalLength": "100",
                "downloadSpeed": "5",
                "files": [{"uris": [{"uri": "https://example.com/file.gguf"}]}],
            },
            {
                "gid": "gid-drop",
                "status": "active",
                "completedLength": "10",
                "totalLength": "100",
                "downloadSpeed": "1",
                "files": [{"uris": [{"uri": "https://example.com/file.gguf"}]}],
            },
        ]
        with (
            patch("ariaflow_server.core.aria2_tell_active", return_value=active),
            patch("ariaflow_server.core.aria_rpc") as rpc,
        ):
            result = deduplicate_active_transfers()
        self.assertTrue(result["changed"])
        self.assertEqual(result["action"], "remove")
        self.assertIn("gid-keep", result["kept"])
        self.assertIn("gid-drop", result["paused"])
        rpc.assert_any_call("aria2.remove", ["gid-drop"], port=6800, timeout=5)

    def test_poll_requeues_item_after_consecutive_rpc_failures(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-1"
        save_queue(items)

        with (
            patch("ariaflow_server.core.aria2_ensure_daemon"),
            patch("ariaflow_server.core.deduplicate_active_transfers"),
            patch("ariaflow_server.core.reconcile_live_queue"),
            patch(
                "ariaflow_server.core.probe_bandwidth",
                return_value={
                    "source": "default",
                    "reason": "probe_unavailable",
                    "cap_mbps": 2,
                    "cap_bytes_per_sec": 250000,
                },
            ),
            patch("ariaflow_server.core.aria2_current_bandwidth", return_value={}),
            patch("ariaflow_server.core.aria2_set_max_overall_download_limit"),
            patch("ariaflow_server.core.aria2_tell_active", return_value=[]),
            patch(
                "ariaflow_server.core.aria2_add_download",
                side_effect=RuntimeError("aria2 still unavailable"),
            ),
            patch(
                "ariaflow_server.core.aria2_tell_status",
                side_effect=RuntimeError("connection refused"),
            ),
            patch(
                "ariaflow_server.core.time.sleep",
                side_effect=[None] * 10 + [StopIteration("stop")],
            ),
        ):
            with self.assertRaises(StopIteration):
                process_queue()
        items = load_queue()
        self.assertEqual(items[0]["status"], "queued")
        self.assertEqual(items[0]["desired_state"], "running")
        self.assertIsNone(items[0].get("gid"))
        self.assertNotIn("error_code", items[0])

    def test_poll_exposes_transient_rpc_timeout_before_terminal_failure(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-1"
        save_queue(items)

        with (
            patch("ariaflow_server.core.aria2_ensure_daemon"),
            patch("ariaflow_server.core.deduplicate_active_transfers"),
            patch("ariaflow_server.core.reconcile_live_queue"),
            patch(
                "ariaflow_server.core.probe_bandwidth",
                return_value={
                    "source": "default",
                    "reason": "probe_unavailable",
                    "cap_mbps": 2,
                    "cap_bytes_per_sec": 250000,
                },
            ),
            patch("ariaflow_server.core.aria2_current_bandwidth", return_value={}),
            patch("ariaflow_server.core.aria2_set_max_overall_download_limit"),
            patch("ariaflow_server.core.aria2_tell_active", return_value=[]),
            patch(
                "ariaflow_server.core.aria2_tell_status",
                side_effect=TimeoutError(),
            ),
            patch(
                "ariaflow_server.core.time.sleep",
                side_effect=[StopIteration("stop")],
            ),
        ):
            with self.assertRaises(StopIteration):
                process_queue()
        items = load_queue()
        self.assertEqual(items[0]["status"], "active")
        self.assertEqual(items[0]["rpc_failures"], 1)
        self.assertEqual(items[0]["rpc_failure_limit"], 5)
        self.assertIn("timed out", items[0]["rpc_error_message"])

    def test_process_queue_marks_completed_tracked_download_done(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        complete = {
            "status": "complete",
            "errorCode": "0",
            "errorMessage": "",
            "downloadSpeed": "0",
            "completedLength": "100",
            "totalLength": "100",
            "files": [{"uris": [{"uri": "https://example.com/model.gguf"}]}],
        }
        with (
            patch("ariaflow_server.core.aria2_ensure_daemon"),
            patch("ariaflow_server.core.deduplicate_active_transfers"),
            patch("ariaflow_server.core.reconcile_live_queue"),
            patch(
                "ariaflow_server.core.probe_bandwidth",
                return_value={
                    "source": "default",
                    "reason": "probe_unavailable",
                    "cap_mbps": 2,
                    "cap_bytes_per_sec": 250000,
                },
            ),
            patch("ariaflow_server.core.aria2_current_bandwidth", return_value={}),
            patch(
                "ariaflow_server.core.aria2_set_max_overall_download_limit"
            ) as aria2_set_max_overall_download_limit,
            patch("ariaflow_server.core.aria2_tell_active", return_value=[]),
            patch("ariaflow_server.core.aria2_add_download", return_value="gid-1"),
            patch("ariaflow_server.core.aria2_tell_status", return_value=complete),
            patch(
                "ariaflow_server.core.time.sleep", side_effect=[None, StopIteration("stop")]
            ),
        ):
            with self.assertRaises(StopIteration):
                process_queue()
        aria2_set_max_overall_download_limit.assert_called_once_with(250000, port=6800)
        items = load_queue()
        self.assertEqual(items[0]["status"], "complete")
        self.assertEqual(items[0]["gid"], "gid-1")
        self.assertIn("post_action", items[0])

    def test_process_queue_does_not_auto_resume_paused_items(self) -> None:
        """Paused items stay paused — user must explicitly resume."""
        add_queue_item("https://example.com/model.gguf")
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["gid"] = "gid-1"
        items[0]["live_status"] = "paused"
        save_queue(items)
        state = load_state()
        state["paused"] = False
        save_state(state)

        class _StopLoop(Exception):
            pass

        def stop_after_one_loop(_seconds: float) -> None:
            raise _StopLoop()

        with (
            patch("ariaflow_server.core.aria2_ensure_daemon"),
            patch("ariaflow_server.core.deduplicate_active_transfers"),
            patch("ariaflow_server.core.reconcile_live_queue"),
            patch(
                "ariaflow_server.core.probe_bandwidth",
                return_value={
                    "source": "default",
                    "reason": "probe_unavailable",
                    "cap_mbps": 2,
                    "cap_bytes_per_sec": 250000,
                },
            ),
            patch("ariaflow_server.core.aria2_current_bandwidth", return_value={}),
            patch("ariaflow_server.core.aria2_set_max_overall_download_limit"),
            patch("ariaflow_server.core.aria2_tell_active", return_value=[]),
            patch(
                "ariaflow_server.core.aria2_tell_status",
                return_value={
                    "status": "paused",
                    "errorCode": "0",
                    "errorMessage": "",
                    "downloadSpeed": "0",
                    "completedLength": "10",
                    "totalLength": "100",
                    "files": [],
                },
            ),
            patch("ariaflow_server.core.aria2_add_download") as aria2_add_download,
            patch("ariaflow_server.core.time.sleep", side_effect=stop_after_one_loop),
        ):
            with self.assertRaises(_StopLoop):
                process_queue()
        # Paused item should NOT have been started
        self.assertFalse(aria2_add_download.called)
        # Item should still be paused in the queue
        items = load_queue()
        self.assertEqual(items[0]["status"], "paused")

    def test_process_queue_reinjects_paused_item_from_memory(self) -> None:
        add_queue_item("https://example.com/linux.torrent")
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["desired_state"] = "paused"
        items[0]["selected_files"] = [1, 3]
        items[0]["gid"] = None
        save_queue(items)
        state = load_state()
        state["running"] = True
        state["paused"] = False
        save_state(state)

        with (
            patch("ariaflow_server.core.aria2_ensure_daemon"),
            patch("ariaflow_server.core.deduplicate_active_transfers"),
            patch("ariaflow_server.core.reconcile_live_queue"),
            patch(
                "ariaflow_server.core.probe_bandwidth",
                return_value={
                    "source": "default",
                    "reason": "probe_unavailable",
                    "cap_mbps": 2,
                    "cap_bytes_per_sec": 250000,
                },
            ),
            patch("ariaflow_server.core.aria2_current_bandwidth", return_value={}),
            patch("ariaflow_server.core.aria2_set_max_overall_download_limit"),
            patch("ariaflow_server.core.aria2_tell_active", return_value=[]),
            patch("ariaflow_server.core.aria2_multicall", return_value=[]),
            patch("ariaflow_server.core.aria2_add_download", return_value="gid-recovered") as add_download,
            patch(
                "ariaflow_server.core.time.sleep",
                side_effect=[StopIteration("stop")],
            ),
        ):
            with self.assertRaises(StopIteration):
                process_queue()
        submitted_item = add_download.call_args.args[0]
        self.assertEqual(submitted_item["desired_state"], "paused")
        self.assertEqual(submitted_item["selected_files"], [1, 3])
        items = load_queue()
        self.assertEqual(items[0]["status"], "paused")
        self.assertEqual(items[0]["desired_state"], "paused")
        self.assertEqual(items[0]["gid"], "gid-recovered")
        self.assertEqual(items[0]["live_status"], "paused")

    def test_ucc_returns_structured_result(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        preflight_result = {
            "contract": "UCC",
            "version": "2.0",
            "gates": [],
            "preferences": [],
            "policies": [],
            "warnings": [],
            "hard_failures": [],
            "status": "pass",
            "exit_code": 0,
        }
        with (
            patch("ariaflow_server.contracts.preflight", return_value=preflight_result),
            patch("ariaflow_server.core.load_queue", return_value=[]),
            patch("ariaflow_server.core.process_queue", return_value=[]),
            patch("ariaflow_server.core.get_active_progress", return_value=None),
        ):
            result = run_ucc()
        self.assertIn("result", result)
        self.assertIn("meta", result)
        self.assertIn("observation", result["result"])
        self.assertIn("outcome", result["result"])

    def test_install_dry_run_is_describable(self) -> None:
        plan = install_all(dry_run=True)
        self.assertIn("ariaflow-server", plan)
        self.assertEqual(plan["ariaflow-server"]["meta"]["contract"], "UCC")
        self.assertEqual(plan["ariaflow-server"]["result"]["observation"], "ok")
        self.assertIn(
            plan["ariaflow-server"]["result"]["outcome"], ["changed", "unchanged"]
        )

    def test_install_dry_run_with_aria2_is_describable(self) -> None:
        plan = install_all(dry_run=True, include_aria2=True)
        aria2_keys = [k for k in plan if k.startswith("aria2-")]
        self.assertEqual(len(aria2_keys), 1)
        self.assertEqual(plan[aria2_keys[0]]["result"]["reason"], "install")

    def test_lifecycle_reports_status_shape(self) -> None:
        status = status_all()
        self.assertIn("ariaflow-server", status)
        self.assertIn("aria2", status)
        self.assertIn("networkquality", status)
        aria2_svc_keys = [k for k in status if k.startswith("aria2-")]
        self.assertEqual(len(aria2_svc_keys), 1)
        self.assertEqual(status["ariaflow-server"]["meta"]["contract"], "UCC")
        self.assertIn(
            status["ariaflow-server"]["result"]["outcome"], ["converged", "unchanged"]
        )

    def test_lifecycle_status_includes_versions(self) -> None:
        with (
            patch("ariaflow_server.install.package_version", return_value="9.9.9"),
            patch("ariaflow_server.install.is_macos", return_value=True),
            patch("ariaflow_server.install.is_windows", return_value=False),
            patch("ariaflow_server.install.is_linux", return_value=False),
            patch("ariaflow_server.install.brew_is_installed", return_value=True),
            patch(
                "ariaflow_server.install.brew_package_version",
                side_effect=["0.1.1", "0.8.2"],
            ),
            patch(
                "ariaflow_server.install.networkquality_status",
                return_value={
                    "installed": True,
                    "usable": True,
                    "version": None,
                    "reason": "ready",
                    "message": "networkquality available",
                },
            ),
            patch(
                "ariaflow_server.platform.launchd.launchd_aria2_status",
                return_value={
                    "loaded": True,
                    "plist_exists": True,
                    "session_exists": True,
                    "version": "1.37.0",
                },
            ),
        ):
            status = status_all()
        self.assertIn("0.1.1", status["ariaflow-server"]["result"]["message"])
        self.assertIn(
            "runtime download dependency", status["aria2"]["result"]["message"]
        )
        self.assertIn(
            "networkquality available", status["networkquality"]["result"]["message"]
        )
        aria2_svc_keys = [k for k in status if k.startswith("aria2-")]
        self.assertEqual(len(aria2_svc_keys), 1)
        self.assertIn(
            "auto-start integration",
            status[aria2_svc_keys[0]]["result"]["message"],
        )

    def test_networkquality_status_reports_availability_without_probe(self) -> None:
        with (
            patch(
                "ariaflow_server.install._find_networkquality",
                return_value="/usr/bin/networkQuality",
            ),
            patch("ariaflow_server.install.subprocess.run") as run,
        ):
            status = networkquality_status()
        self.assertFalse(run.called)
        self.assertTrue(status["installed"])
        self.assertTrue(status["usable"])
        self.assertEqual(status["reason"], "ready")
        self.assertIn(
            "bounded -u -c -s probes at startup and every 180s", str(status["message"])
        )

    def test_uninstall_dry_run_is_describable(self) -> None:
        plan = uninstall_all(dry_run=True)
        self.assertIn("ariaflow-server", plan)
        self.assertEqual(plan["ariaflow-server"]["meta"]["contract"], "UCC")
        self.assertIn(
            plan["ariaflow-server"]["result"]["reason"], ["uninstall", "info"]
        )

    def test_uninstall_dry_run_with_aria2_is_describable(self) -> None:
        plan = uninstall_all(dry_run=True, include_aria2=True)
        aria2_keys = [k for k in plan if k.startswith("aria2-")]
        self.assertEqual(len(aria2_keys), 1)
        self.assertEqual(plan[aria2_keys[0]]["result"]["reason"], "uninstall")


class TicPerItemTests(IsolatedTestCase):
    """Per-item action API tests."""

    def test_pause_queue_item_sets_paused(self) -> None:
        from ariaflow_server.core import pause_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        result = pause_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item"]["status"], "paused")

    def test_pause_queue_item_calls_aria2_if_gid(self) -> None:
        from ariaflow_server.core import pause_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("ariaflow_server.core.aria_rpc") as rpc:
            result = pause_queue_item(item.id)
        rpc.assert_any_call("aria2.pause", ["gid-1"], port=6800, timeout=5)
        self.assertEqual(result["item"]["status"], "paused")

    def test_resume_queue_item_from_paused(self) -> None:
        from ariaflow_server.core import pause_queue_item, resume_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        pause_queue_item(item.id)
        result = resume_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item"]["status"], "queued")

    def test_resume_queue_item_with_gid_calls_unpause(self) -> None:
        from ariaflow_server.core import resume_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("ariaflow_server.core.aria_rpc"):
            result = resume_queue_item(item.id)
        self.assertEqual(result["item"]["status"], "active")

    def test_remove_queue_item_deletes_from_queue(self) -> None:
        from ariaflow_server.core import remove_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        result = remove_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertTrue(result["removed"])
        self.assertEqual(len(load_queue()), 0)

    def test_remove_active_item_calls_aria2_remove(self) -> None:
        from ariaflow_server.core import remove_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "active"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("ariaflow_server.core.aria_rpc") as rpc:
            remove_queue_item(item.id)
        rpc.assert_any_call("aria2.remove", ["gid-1"], port=6800, timeout=5)
        self.assertEqual(len(load_queue()), 0)

    def test_retry_queue_item_requeues_failed(self) -> None:
        from ariaflow_server.core import retry_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "error"
        items[0]["error_code"] = "1"
        items[0]["error_message"] = "download failed"
        save_queue(items)
        result = retry_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item"]["status"], "queued")
        self.assertNotIn("error_code", result["item"])
        self.assertNotIn("gid", result["item"])

    def test_retry_rejects_non_error_item(self) -> None:
        from ariaflow_server.core import retry_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        result = retry_queue_item(item.id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_state")

    def test_pause_rejects_already_paused(self) -> None:
        from ariaflow_server.core import pause_queue_item

        item = add_queue_item("https://example.com/file.gguf")
        pause_queue_item(item.id)
        result = pause_queue_item(item.id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_state")

    def test_not_found_item(self) -> None:
        from ariaflow_server.core import pause_queue_item

        result = pause_queue_item("nonexistent")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")


class TicTorrentAndOptionsTests(IsolatedTestCase):
    """Torrent file selection, metadata URL detection, and aria2 options proxy tests."""

    def test_metadata_url_detection(self) -> None:
        from ariaflow_server.core import _is_metadata_url

        self.assertTrue(_is_metadata_url("https://example.com/file.torrent"))
        self.assertTrue(_is_metadata_url("https://example.com/file.metalink"))
        self.assertTrue(_is_metadata_url("https://example.com/file.meta4"))
        self.assertTrue(_is_metadata_url("magnet:?xt=urn:btih:abc123"))
        self.assertFalse(_is_metadata_url("https://example.com/file.zip"))
        self.assertFalse(_is_metadata_url("https://example.com/file.gguf"))

    def test_add_download_sets_pause_metadata_for_torrent(self) -> None:
        from ariaflow_server.core import aria2_add_download

        item = {"url": "https://example.com/file.torrent", "mode": "torrent"}
        with patch("ariaflow_server.core.aria_rpc", return_value={"result": "gid-1"}) as rpc:
            gid = aria2_add_download(item, cap_bytes_per_sec=250000)
        call_args = rpc.call_args[0]
        options = call_args[1][1]
        self.assertEqual(options["pause-metadata"], "true")
        self.assertEqual(gid, "gid-1")

    def test_add_download_no_pause_metadata_for_http(self) -> None:
        from ariaflow_server.core import aria2_add_download

        item = {"url": "https://example.com/file.zip", "mode": "http"}
        with patch("ariaflow_server.core.aria_rpc", return_value={"result": "gid-1"}) as rpc:
            aria2_add_download(item, cap_bytes_per_sec=250000)
        call_args = rpc.call_args[0]
        options = call_args[1][1]
        self.assertNotIn("pause-metadata", options)

    def test_add_download_pauses_when_desired_state_is_paused(self) -> None:
        from ariaflow_server.core import aria2_add_download

        item = {"url": "https://example.com/file.zip", "mode": "http", "desired_state": "paused"}
        with patch("ariaflow_server.core.aria_rpc", return_value={"result": "gid-1"}) as rpc:
            aria2_add_download(item, cap_bytes_per_sec=250000)
        call_args = rpc.call_args[0]
        options = call_args[1][1]
        self.assertEqual(options["pause"], "true")

    def test_add_download_applies_saved_selected_files(self) -> None:
        from ariaflow_server.core import aria2_add_download

        item = {
            "url": "https://example.com/file.torrent",
            "mode": "torrent",
            "selected_files": [1, 4],
        }
        with patch("ariaflow_server.core.aria_rpc", return_value={"result": "gid-1"}) as rpc:
            aria2_add_download(item, cap_bytes_per_sec=250000)
        call_args = rpc.call_args[0]
        options = call_args[1][1]
        self.assertEqual(options["select-file"], "1,4")

    def test_get_item_files_returns_file_list(self) -> None:
        from ariaflow_server.core import get_item_files

        item = add_queue_item("https://example.com/file.torrent")
        items = load_queue()
        items[0]["gid"] = "gid-1"
        save_queue(items)
        files = [
            {
                "index": "1",
                "path": "/tmp/file1.txt",
                "length": "100",
                "selected": "true",
            }
        ]
        with patch("ariaflow_server.core.aria_rpc", return_value={"result": files}):
            result = get_item_files(item.id)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["index"], "1")

    def test_get_item_files_no_gid(self) -> None:
        from ariaflow_server.core import get_item_files

        item = add_queue_item("https://example.com/file.torrent")
        result = get_item_files(item.id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_gid")

    def test_select_item_files_calls_change_option_and_unpause(self) -> None:
        from ariaflow_server.core import select_item_files

        item = add_queue_item("https://example.com/file.torrent")
        items = load_queue()
        items[0]["gid"] = "gid-1"
        items[0]["status"] = "paused"
        save_queue(items)
        with patch("ariaflow_server.core.aria_rpc") as rpc:
            result = select_item_files(item.id, [1, 3])
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected"], [1, 3])
        rpc.assert_any_call(
            "aria2.changeOption",
            ["gid-1", {"select-file": "1,3"}],
            port=6800,
            timeout=5,
        )
        rpc.assert_any_call("aria2.unpause", ["gid-1"], port=6800, timeout=5)
        items = load_queue()
        self.assertEqual(items[0]["selected_files"], [1, 3])
        self.assertEqual(items[0]["desired_state"], "running")

    def test_change_aria2_options_safe_subset(self) -> None:
        from ariaflow_server.core import aria2_change_options

        with (
            patch("ariaflow_server.core.aria_rpc") as rpc,
            patch("ariaflow_server.core.aria2_current_global_options", return_value={}),
        ):
            result = aria2_change_options({"max-concurrent-downloads": "3"})
        self.assertTrue(result["ok"])
        rpc.assert_any_call(
            "aria2.changeGlobalOption",
            [{"max-concurrent-downloads": "3"}],
            port=6800,
            timeout=5,
        )

    def test_change_aria2_options_rejects_unsafe(self) -> None:
        from ariaflow_server.core import aria2_change_options

        result = aria2_change_options(
            {"dir": "/tmp/evil", "max-concurrent-downloads": "3"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "rejected_options")
        self.assertIn("dir", result["message"])

    def test_change_aria2_options_rejects_empty(self) -> None:
        from ariaflow_server.core import aria2_change_options

        result = aria2_change_options({})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "empty_options")


class TicOpenAPITests(unittest.TestCase):
    """Validate OpenAPI spec is well-formed."""

    def test_openapi_spec_is_valid_yaml(self) -> None:
        spec_path = Path(__file__).resolve().parents[1] / "openapi.yaml"
        self.assertTrue(spec_path.exists(), "openapi.yaml not found")
        text = spec_path.read_text(encoding="utf-8")
        try:
            import yaml

            data = yaml.safe_load(text)
        except ImportError:
            self.skipTest("PyYAML not installed")
            return
        self.assertEqual(data["openapi"], "3.0.3")
        self.assertIn("paths", data)
        self.assertIn("/api/status", data["paths"])
        self.assertIn("/api/downloads/{id}/pause", data["paths"])
        self.assertIn("/api/aria2/change_global_option", data["paths"])


class TicAsmCoherenceTests(IsolatedTestCase):
    """
    Name: test_tic_asm_coherence
    Intent: pin the explicit ASM coherence-rule guards added to ariaflow.
    Scope: state.py (CR-4), scheduler.py (CR-3 crash handler)
    Trace targets: ASM CR-3, ASM CR-4
    """

    def test_cr4_close_session_refuses_with_active_jobs(self) -> None:
        # ASM CR-4: a session may not transition to closed while jobs are
        # in the active or waiting tier. close_state_session must raise.
        from ariaflow_server.core import (
            close_state_session,
            ensure_state_session,
            save_queue,
        )

        ensure_state_session()
        save_queue(
            [
                {"id": "j1", "url": "https://example.com/a.bin", "status": "active"},
            ]
        )
        with self.assertRaises(RuntimeError) as ctx:
            close_state_session("test")
        self.assertIn("CR-4", str(ctx.exception))

    def test_cr4_rollover_pauses_active_jobs_before_close(self) -> None:
        # ASM CR-4: start_new_state_session must pause active/waiting items
        # in queue.json before invoking close, so the rollover transition
        # is admissible.
        from ariaflow_server.core import (
            ensure_state_session,
            load_queue,
            save_queue,
            start_new_state_session,
        )

        ensure_state_session()
        save_queue(
            [
                {"id": "j1", "url": "https://example.com/a.bin", "status": "active"},
                {"id": "j2", "url": "https://example.com/b.bin", "status": "waiting"},
                {"id": "j3", "url": "https://example.com/c.bin", "status": "queued"},
            ]
        )
        start_new_state_session("test_rollover")
        items = {it["id"]: it["status"] for it in load_queue()}
        self.assertEqual(items["j1"], "paused")
        self.assertEqual(items["j2"], "paused")
        self.assertEqual(items["j3"], "queued")  # untouched

    def test_cr3_scheduler_crash_pauses_aria2(self) -> None:
        # ASM CR-3: when run leaves the running state via the crash handler,
        # the source-of-truth (aria2) must stop transferring before
        # running=False is written to ariaflow's mirror.
        import time as _time
        from ariaflow_server import scheduler

        crash = RuntimeError("simulated process_queue crash")
        with (
            patch("ariaflow_server.core.process_queue", side_effect=crash),
            patch("ariaflow_server.core.aria2_pause_all") as pause_all,
            patch(
                "ariaflow_server.core.ensure_state_session", return_value={"running": False}
            ),
            patch("ariaflow_server.core.save_state"),
            patch("ariaflow_server.core.load_state", return_value={}),
            patch("ariaflow_server.core.storage_locked"),
        ):
            scheduler.start_background_process(port=6800)
            # Background thread is daemon=True; give it a moment to crash.
            for _ in range(50):
                if pause_all.called:
                    break
                _time.sleep(0.02)
        pause_all.assert_called_once()

    def test_cr3_crash_handler_swallows_pause_failure(self) -> None:
        # ASM CR-3 best-effort: if aria2 itself is the cause of the crash,
        # aria2_pause_all may fail. The handler must still complete and
        # write running=False so the mirror reflects the stop.
        import time as _time
        from ariaflow_server import scheduler

        crash = RuntimeError("simulated process_queue crash")
        with (
            patch("ariaflow_server.core.process_queue", side_effect=crash),
            patch(
                "ariaflow_server.core.aria2_pause_all",
                side_effect=ConnectionError("daemon dead"),
            ),
            patch(
                "ariaflow_server.core.ensure_state_session", return_value={"running": False}
            ),
            patch("ariaflow_server.core.save_state") as save_state_mock,
            patch("ariaflow_server.core.load_state", return_value={}),
            patch("ariaflow_server.core.storage_locked"),
        ):
            scheduler.start_background_process(port=6800)
            for _ in range(50):
                if save_state_mock.called:
                    break
                _time.sleep(0.02)
        save_state_mock.assert_called()
        written = save_state_mock.call_args[0][0]
        self.assertFalse(written["running"])
        self.assertIn("simulated process_queue crash", written.get("last_error", ""))


if __name__ == "__main__":
    unittest.main()
