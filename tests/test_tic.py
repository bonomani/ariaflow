from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aria_queue.contracts import preflight, run_ucc
from aria_queue.core import (
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
from aria_queue.install import install_all, networkquality_status, status_all, uninstall_all


class TicAriaFlowTests(unittest.TestCase):
    """
    Name: test_tic
    Intent: verify queue enqueueing, preflight reporting, and structured UCC output.
    Scope: ariaflow command layer
    Trace targets: UIC pre-flight, UCC execution, TIC reporting
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_enqueue_creates_queue_item(self) -> None:
        item = add_queue_item("https://example.com/model.gguf")
        self.assertTrue(item.id)
        self.assertEqual(item.status, "queued")
        self.assertTrue(item.session_id)
        from aria_queue.core import load_state
        state = load_state()
        self.assertTrue(state.get("session_started_at"))
        self.assertTrue(state.get("session_last_seen_at"))
        log = load_action_log()
        add_entry = next(entry for entry in reversed(log) if entry.get("action") == "add")
        self.assertIn("session_id", add_entry)
        self.assertIn("observed_before", add_entry)
        self.assertIn("observed_after", add_entry)

    def test_new_session_closes_previous_and_starts_fresh(self) -> None:
        first = add_queue_item("https://example.com/one.gguf")
        state_before = load_state()
        next_state = start_new_state_session()
        self.assertNotEqual(state_before.get("session_id"), next_state.get("session_id"))
        self.assertTrue(next_state.get("session_started_at"))
        self.assertIsNone(next_state.get("session_closed_at"))
        self.assertEqual(first.session_id, state_before.get("session_id"))

    def test_enqueue_reuses_duplicate_url(self) -> None:
        first = add_queue_item("https://example.com/model.gguf")
        second = add_queue_item("https://example.com/model.gguf")
        self.assertEqual(first.id, second.id)
        log = load_action_log()
        duplicate_entry = next(entry for entry in reversed(log) if entry.get("reason") == "duplicate_url")
        self.assertEqual(duplicate_entry["outcome"], "unchanged")

    def test_preflight_emits_gate_results(self) -> None:
        with patch("aria_queue.contracts.aria_rpc", return_value={"result": {"version": "1.37.0"}}), \
             patch("aria_queue.contracts.ensure_aria_daemon") as ensure:
            result = preflight()
        self.assertIn("gates", result)
        self.assertIn("status", result)
        self.assertIn(result["exit_code"], [0, 1])
        self.assertNotIn("action_log", result)
        self.assertFalse(ensure.called)

    def test_preflight_bootstraps_aria2_when_rpc_is_initially_unavailable(self) -> None:
        with patch(
            "aria_queue.contracts.aria_rpc",
            side_effect=[RuntimeError("offline"), {"result": {"version": "1.37.0"}}],
        ), patch("aria_queue.contracts.ensure_aria_daemon") as ensure:
            result = preflight()
        gate = next(gate for gate in result["gates"] if gate["name"] == "aria2_available")
        self.assertTrue(gate["satisfied"])
        ensure.assert_called_once_with(port=6800)

    def test_auto_preflight_default_is_disabled(self) -> None:
        from aria_queue.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        auto = next((pref for pref in prefs if pref.get("name") == "auto_preflight_on_run"), {})
        self.assertFalse(auto.get("value", True))

    def test_concurrency_default_is_sequential(self) -> None:
        from aria_queue.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        limit = next((pref for pref in prefs if pref.get("name") == "max_simultaneous_downloads"), {})
        self.assertEqual(limit.get("value", 0), 1)

    def test_duplicate_active_transfer_default_is_remove(self) -> None:
        from aria_queue.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        dedup = next((pref for pref in prefs if pref.get("name") == "duplicate_active_transfer_action"), {})
        self.assertEqual(dedup.get("value"), "remove")

    def test_probe_fallback_reports_reason(self) -> None:
        with patch("aria_queue.core._find_networkquality", return_value=None):
            result = probe_bandwidth()
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["reason"], "probe_unavailable")
        self.assertIn("cap_mbps", result)
        self.assertEqual(result["cap_bytes_per_sec"], 250000)

    def test_probe_uses_machine_readable_networkquality_output(self) -> None:
        output = json.dumps({"dl_throughput": 80_000_000, "dl_responsiveness": 1200, "interface_name": "en0"})
        with patch("aria_queue.core._find_networkquality", return_value="/usr/bin/networkQuality"), \
             patch("aria_queue.core.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=output)) as run:
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
        with patch("aria_queue.core._find_networkquality", return_value="/usr/bin/networkQuality"), \
             patch("aria_queue.core.subprocess.run", side_effect=timeout):
            result = probe_bandwidth()
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["reason"], "probe_timeout_no_parse")
        self.assertTrue(result["partial"])
        self.assertEqual(result["cap_bytes_per_sec"], 250000)

    def test_should_probe_bandwidth_uses_interval(self) -> None:
        self.assertTrue(_should_probe_bandwidth({}))
        self.assertFalse(_should_probe_bandwidth({"last_bandwidth_probe_at": 100.0}, now=200.0))
        self.assertTrue(_should_probe_bandwidth({"last_bandwidth_probe_at": 100.0}, now=281.0))

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
        with patch("aria_queue.core.time.time", return_value=120.0), \
             patch("aria_queue.core.probe_bandwidth") as probe_bandwidth_mock, \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth") as set_bandwidth_mock, \
             patch("aria_queue.core.record_action") as record_action_mock:
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
        with patch("aria_queue.core.time.time", return_value=400.0), \
             patch("aria_queue.core.probe_bandwidth", return_value=fresh_probe) as probe_bandwidth_mock, \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth") as set_bandwidth_mock, \
             patch("aria_queue.core.record_action") as record_action_mock:
            probe, cap_mbps, cap_bytes_per_sec = _apply_bandwidth_probe(state=state)
        probe_bandwidth_mock.assert_called_once()
        set_bandwidth_mock.assert_called_once_with(4_000_000, port=6800)
        record_action_mock.assert_called_once()
        self.assertEqual(cap_mbps, 32.0)
        self.assertEqual(cap_bytes_per_sec, 4_000_000)
        self.assertEqual(probe["interval_seconds"], 180)
        self.assertEqual(state["last_bandwidth_probe_at"], 400.0)

    def test_discover_active_transfer_prefers_state_gid(self) -> None:
        with patch("aria_queue.core.load_state", return_value={"active_gid": "gid-1", "active_url": "https://example.com/a.gguf"}), \
             patch("aria_queue.core.status", return_value={"status": "active", "completedLength": "10", "totalLength": "100", "downloadSpeed": "5"}):
            active = discover_active_transfer()
        self.assertEqual(active["gid"], "gid-1")
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["percent"], 10.0)

    def test_discover_active_transfer_recovers_url_from_queue(self) -> None:
        with patch("aria_queue.core.load_state", return_value={"active_gid": "gid-1", "active_url": None}), \
             patch("aria_queue.core.load_queue", return_value=[{"id": "item-1", "url": "https://example.com/recovered.gguf", "status": "paused", "gid": "gid-1"}]), \
             patch("aria_queue.core.status", return_value={"status": "active", "completedLength": "10", "totalLength": "100", "downloadSpeed": "5"}):
            active = discover_active_transfer()
        self.assertEqual(active["gid"], "gid-1")
        self.assertEqual(active["url"], "https://example.com/recovered.gguf")

    def test_reconcile_promotes_paused_item_to_downloading_when_live_active(self) -> None:
        queue_item = {"id": "item-1", "url": "https://example.com/file.gguf", "status": "paused", "gid": "gid-1", "session_id": "batch-1"}
        live = [{"gid": "gid-1", "status": "active", "completedLength": "50", "totalLength": "100", "downloadSpeed": "10", "files": [{"uris": [{"uri": "https://example.com/file.gguf"}]}]}]
        with patch("aria_queue.core.load_state", return_value={"session_id": "batch-1"}), \
             patch("aria_queue.core.active_gids", return_value=live), \
             patch("aria_queue.core.load_queue", return_value=[queue_item]), \
             patch("aria_queue.core.save_queue") as save_queue, \
             patch("aria_queue.core.record_action"):
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        saved = save_queue.call_args[0][0]
        self.assertEqual(saved[0]["status"], "downloading")

    def test_reconcile_live_queue_adopts_unmatched_active_job(self) -> None:
        with patch("aria_queue.core.load_state", return_value={"session_id": "batch-1"}), \
             patch("aria_queue.core.active_gids", return_value=[{"gid": "gid-9", "status": "active", "completedLength": "5", "totalLength": "100", "downloadSpeed": "10", "files": [{"uris": [{"uri": "https://example.com/new.gguf"}]}]}]), \
             patch("aria_queue.core.load_queue", return_value=[]), \
             patch("aria_queue.core.save_queue") as save_queue, \
             patch("aria_queue.core.record_action") as record_action:
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        self.assertEqual(result["recovered"], 1)
        save_queue.assert_called_once()
        record_action.assert_called_once()

    def test_reconcile_live_queue_updates_old_session_item_in_place(self) -> None:
        with patch("aria_queue.core.load_state", return_value={"session_id": "batch-2"}), \
             patch("aria_queue.core.active_gids", return_value=[{"gid": "gid-9", "status": "active", "completedLength": "50", "totalLength": "100", "downloadSpeed": "10", "files": [{"uris": [{"uri": "https://example.com/file.gguf"}]}]}]), \
             patch("aria_queue.core.load_queue", return_value=[{"id": "item-1", "url": "https://example.com/file.gguf", "status": "paused", "gid": "gid-old", "session_id": "batch-1"}]), \
             patch("aria_queue.core.save_queue") as save_queue, \
             patch("aria_queue.core.record_action") as record_action:
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        self.assertEqual(result["recovered"], 1)
        saved_items = save_queue.call_args[0][0]
        self.assertEqual(saved_items[0]["session_id"], "batch-2")
        self.assertEqual(saved_items[0]["recovery_session_id"], "batch-2")
        record_action.assert_called_once()

    def test_reconcile_live_queue_collapses_duplicate_rows_for_same_live_download(self) -> None:
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
                "status": "downloading",
                "gid": "gid-9",
                "session_id": "batch-2",
                "completedLength": "230300000",
                "recovered": True,
            },
        ]
        live = [{
            "gid": "gid-9",
            "status": "active",
            "completedLength": "230300000",
            "totalLength": "3200000000",
            "downloadSpeed": "10",
            "files": [{"uris": [{"uri": "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso"}]}],
        }]
        saved_items: list[dict] = []

        def capture_save(items: list[dict]) -> None:
            saved_items[:] = items

        with patch("aria_queue.core.load_state", return_value={"session_id": "batch-3"}), \
             patch("aria_queue.core.active_gids", return_value=live), \
             patch("aria_queue.core.load_queue", return_value=queue_items), \
             patch("aria_queue.core.save_queue", side_effect=capture_save), \
             patch("aria_queue.core.record_action") as record_action:
            result = reconcile_live_queue()
        self.assertTrue(result["changed"])
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(len(saved_items), 1)
        self.assertEqual(saved_items[0]["gid"], "gid-9")
        self.assertEqual(saved_items[0]["url"], "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso")
        self.assertEqual(saved_items[0]["completedLength"], "230300000")
        self.assertTrue(saved_items[0]["recovered"])
        record_action.assert_called_once()

    def test_deduplicate_active_transfers_removes_less_advanced_duplicates_by_default(self) -> None:
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
        with patch("aria_queue.core.active_gids", return_value=active), \
             patch("aria_queue.core.aria_rpc") as rpc:
            result = deduplicate_active_transfers()
        self.assertTrue(result["changed"])
        self.assertEqual(result["action"], "remove")
        self.assertIn("gid-keep", result["kept"])
        self.assertIn("gid-drop", result["paused"])
        rpc.assert_any_call("aria2.remove", ["gid-drop"], port=6800, timeout=5)

    def test_poll_marks_item_error_after_consecutive_rpc_failures(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        items = load_queue()
        items[0]["status"] = "downloading"
        items[0]["gid"] = "gid-1"
        save_queue(items)

        with patch("aria_queue.core.ensure_aria_daemon"), \
             patch("aria_queue.core.deduplicate_active_transfers"), \
             patch("aria_queue.core.reconcile_live_queue"), \
             patch("aria_queue.core.probe_bandwidth", return_value={"source": "default", "reason": "probe_unavailable", "cap_mbps": 2, "cap_bytes_per_sec": 250000}), \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth"), \
             patch("aria_queue.core.active_gids", return_value=[]), \
             patch("aria_queue.core.status", side_effect=RuntimeError("connection refused")), \
             patch("aria_queue.core.time.sleep", return_value=None):
            result = process_queue()
        self.assertEqual(result[0]["status"], "error")
        self.assertEqual(result[0]["error_code"], "rpc_unreachable")
        self.assertIn("5", result[0]["error_message"])

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
        with patch("aria_queue.core.ensure_aria_daemon"), \
             patch("aria_queue.core.deduplicate_active_transfers"), \
             patch("aria_queue.core.reconcile_live_queue"), \
             patch("aria_queue.core.probe_bandwidth", return_value={"source": "default", "reason": "probe_unavailable", "cap_mbps": 2, "cap_bytes_per_sec": 250000}), \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.set_bandwidth") as set_bandwidth, \
             patch("aria_queue.core.active_gids", return_value=[]), \
             patch("aria_queue.core.add_download", return_value="gid-1"), \
             patch("aria_queue.core.status", return_value=complete), \
             patch("aria_queue.core.time.sleep", return_value=None):
            result = process_queue()
        set_bandwidth.assert_called_once_with(250000, port=6800)
        self.assertEqual(result[0]["status"], "done")
        self.assertEqual(result[0]["gid"], "gid-1")
        self.assertIn("post_action", result[0])

    def test_process_queue_resumes_paused_tracked_download(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["gid"] = "gid-1"
        items[0]["live_status"] = "paused"
        save_queue(items)
        state = load_state()
        state["paused"] = False
        save_state(state)

        status_responses = iter(
            [
                {
                    "status": "paused",
                    "errorCode": "0",
                    "errorMessage": "",
                    "downloadSpeed": "0",
                    "completedLength": "10",
                    "totalLength": "100",
                    "files": [{"uris": [{"uri": "https://example.com/model.gguf"}]}],
                },
                {
                    "status": "complete",
                    "errorCode": "0",
                    "errorMessage": "",
                    "downloadSpeed": "0",
                    "completedLength": "100",
                    "totalLength": "100",
                    "files": [{"uris": [{"uri": "https://example.com/model.gguf"}]}],
                },
            ]
        )

        def fake_status(_gid: str, port: int = 6800, timeout: int = 5) -> dict:
            return next(status_responses)

        with patch("aria_queue.core.ensure_aria_daemon"), \
             patch("aria_queue.core.deduplicate_active_transfers"), \
             patch("aria_queue.core.reconcile_live_queue"), \
             patch("aria_queue.core.probe_bandwidth", return_value={"source": "default", "reason": "probe_unavailable", "cap_mbps": 2, "cap_bytes_per_sec": 250000}), \
             patch("aria_queue.core.current_bandwidth", return_value={}), \
             patch("aria_queue.core.active_gids", return_value=[]), \
             patch("aria_queue.core.add_download") as add_download, \
             patch("aria_queue.core.status", side_effect=fake_status), \
             patch("aria_queue.core.aria_rpc", return_value={"result": "gid-1"}) as rpc, \
             patch("aria_queue.core.time.sleep", return_value=None):
            result = process_queue()
        self.assertFalse(add_download.called)
        rpc.assert_any_call("aria2.changeOption", ["gid-1", {"max-download-limit": "250000"}], port=6800, timeout=5)
        rpc.assert_any_call("aria2.unpause", ["gid-1"], port=6800, timeout=5)
        self.assertEqual(result[0]["status"], "done")

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
        with patch("aria_queue.contracts.preflight", return_value=preflight_result), \
             patch("aria_queue.core.load_queue", return_value=[]), \
             patch("aria_queue.core.process_queue", return_value=[]), \
             patch("aria_queue.core.get_active_progress", return_value=None):
            result = run_ucc()
        self.assertIn("result", result)
        self.assertIn("meta", result)
        self.assertIn("observation", result["result"])
        self.assertIn("outcome", result["result"])

    def test_install_dry_run_is_describable(self) -> None:
        plan = install_all(dry_run=True)
        self.assertIn("ariaflow", plan)
        self.assertNotIn("aria2-launchd", plan)
        self.assertEqual(plan["ariaflow"]["meta"]["contract"], "UCC")
        self.assertEqual(plan["ariaflow"]["result"]["observation"], "ok")
        self.assertEqual(plan["ariaflow"]["result"]["outcome"], "changed")

    def test_install_dry_run_with_aria2_is_describable(self) -> None:
        plan = install_all(dry_run=True, include_aria2=True)
        self.assertIn("aria2-launchd", plan)
        self.assertEqual(plan["aria2-launchd"]["result"]["reason"], "install")

    def test_lifecycle_reports_status_shape(self) -> None:
        status = status_all()
        self.assertIn("ariaflow", status)
        self.assertIn("aria2", status)
        self.assertIn("networkquality", status)
        self.assertIn("aria2-launchd", status)
        self.assertEqual(status["ariaflow"]["meta"]["contract"], "UCC")
        self.assertIn(status["ariaflow"]["result"]["outcome"], ["converged", "unchanged"])

    def test_lifecycle_status_includes_versions(self) -> None:
        with patch("aria_queue.install.package_version", return_value="9.9.9"), \
             patch("aria_queue.install.brew_is_installed", return_value=True), \
             patch("aria_queue.install.brew_package_version", side_effect=["0.1.1", "0.8.2"]), \
             patch("aria_queue.install.networkquality_status", return_value={"installed": True, "usable": True, "version": None, "reason": "ready", "message": "networkquality available"}), \
             patch("aria_queue.install.aria2_status", return_value={"loaded": True, "plist_exists": True, "session_exists": True, "version": "1.37.0"}):
            status = status_all()
        self.assertIn("0.1.1", status["ariaflow"]["result"]["message"])
        self.assertIn("runtime engine dependency", status["aria2"]["result"]["message"])
        self.assertIn("networkquality available", status["networkquality"]["result"]["message"])
        self.assertIn("optional advanced auto-start integration", status["aria2-launchd"]["result"]["message"])

    def test_networkquality_status_reports_availability_without_probe(self) -> None:
        with patch("aria_queue.install._find_networkquality", return_value="/usr/bin/networkQuality"), \
             patch("aria_queue.install.subprocess.run") as run:
            status = networkquality_status()
        self.assertFalse(run.called)
        self.assertTrue(status["installed"])
        self.assertTrue(status["usable"])
        self.assertEqual(status["reason"], "ready")
        self.assertIn("bounded -u -c -s probes at startup and every 180s", str(status["message"]))

    def test_uninstall_dry_run_is_describable(self) -> None:
        plan = uninstall_all(dry_run=True)
        self.assertIn("ariaflow", plan)
        self.assertNotIn("aria2-launchd", plan)
        self.assertEqual(plan["ariaflow"]["meta"]["contract"], "UCC")
        self.assertEqual(plan["ariaflow"]["result"]["reason"], "uninstall")

    def test_uninstall_dry_run_with_aria2_is_describable(self) -> None:
        plan = uninstall_all(dry_run=True, include_aria2=True)
        self.assertIn("aria2-launchd", plan)
        self.assertEqual(plan["aria2-launchd"]["result"]["reason"], "uninstall")


class TicPerItemTests(unittest.TestCase):
    """Per-item action API tests."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["ARIA_QUEUE_DIR"] = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pause_queue_item_sets_paused(self) -> None:
        from aria_queue.core import pause_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        result = pause_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item"]["status"], "paused")

    def test_pause_queue_item_calls_aria2_if_gid(self) -> None:
        from aria_queue.core import pause_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "downloading"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("aria_queue.core.aria_rpc") as rpc:
            result = pause_queue_item(item.id)
        rpc.assert_any_call("aria2.pause", ["gid-1"], port=6800, timeout=5)
        self.assertEqual(result["item"]["status"], "paused")

    def test_resume_queue_item_from_paused(self) -> None:
        from aria_queue.core import pause_queue_item, resume_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        pause_queue_item(item.id)
        result = resume_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item"]["status"], "queued")

    def test_resume_queue_item_with_gid_calls_unpause(self) -> None:
        from aria_queue.core import resume_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "paused"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("aria_queue.core.aria_rpc"):
            result = resume_queue_item(item.id)
        self.assertEqual(result["item"]["status"], "downloading")

    def test_remove_queue_item_deletes_from_queue(self) -> None:
        from aria_queue.core import remove_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        result = remove_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertTrue(result["removed"])
        self.assertEqual(len(load_queue()), 0)

    def test_remove_active_item_calls_aria2_remove(self) -> None:
        from aria_queue.core import remove_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "downloading"
        items[0]["gid"] = "gid-1"
        save_queue(items)
        with patch("aria_queue.core.aria_rpc") as rpc:
            result = remove_queue_item(item.id)
        rpc.assert_any_call("aria2.remove", ["gid-1"], port=6800, timeout=5)
        self.assertEqual(len(load_queue()), 0)

    def test_retry_queue_item_requeues_failed(self) -> None:
        from aria_queue.core import retry_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        items = load_queue()
        items[0]["status"] = "error"
        items[0]["error_code"] = "1"
        items[0]["error_message"] = "download failed"
        save_queue(items)
        result = retry_queue_item(item.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item"]["status"], "queued")
        self.assertIsNone(result["item"]["error_code"])
        self.assertIsNone(result["item"]["gid"])

    def test_retry_rejects_non_error_item(self) -> None:
        from aria_queue.core import retry_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        result = retry_queue_item(item.id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_state")

    def test_pause_rejects_already_paused(self) -> None:
        from aria_queue.core import pause_queue_item
        item = add_queue_item("https://example.com/file.gguf")
        pause_queue_item(item.id)
        result = pause_queue_item(item.id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_state")

    def test_not_found_item(self) -> None:
        from aria_queue.core import pause_queue_item
        result = pause_queue_item("nonexistent")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
