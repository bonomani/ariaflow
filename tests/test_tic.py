from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aria_queue.contracts import preflight, run_ucc
from aria_queue.core import add_queue_item, deduplicate_active_transfers, discover_active_transfer, load_action_log, probe_bandwidth, start_new_state_session, load_state
from aria_queue.install import install_all, status_all, uninstall_all


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
        result = preflight()
        self.assertIn("gates", result)
        self.assertIn("status", result)
        self.assertIn(result["exit_code"], [0, 1])
        self.assertNotIn("action_log", result)

    def test_auto_preflight_default_is_disabled(self) -> None:
        from aria_queue.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        auto = next((pref for pref in prefs if pref.get("name") == "auto_preflight_on_run"), {})
        self.assertFalse(auto.get("value", True))

    def test_concurrency_default_is_unlimited(self) -> None:
        from aria_queue.contracts import load_declaration

        declaration = load_declaration()
        prefs = declaration.get("uic", {}).get("preferences", [])
        limit = next((pref for pref in prefs if pref.get("name") == "max_simultaneous_downloads"), {})
        self.assertEqual(limit.get("value", 1), 0)

    def test_probe_fallback_reports_reason(self) -> None:
        with patch("aria_queue.core.shutil.which", return_value=None):
            result = probe_bandwidth()
        self.assertEqual(result["source"], "default")
        self.assertEqual(result["reason"], "probe_unavailable")
        self.assertIn("cap_mbps", result)

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

    def test_deduplicate_active_transfers_pauses_less_advanced_duplicates(self) -> None:
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
        self.assertIn("gid-keep", result["kept"])
        self.assertIn("gid-drop", result["paused"])
        rpc.assert_any_call("aria2.pause", ["gid-drop"], port=6800, timeout=5)

    def test_ucc_returns_structured_result(self) -> None:
        add_queue_item("https://example.com/model.gguf")
        result = run_ucc()
        self.assertIn("result", result)
        self.assertIn("meta", result)
        self.assertIn("observation", result["result"])
        self.assertIn("outcome", result["result"])

    def test_install_dry_run_is_describable(self) -> None:
        plan = install_all(dry_run=True)
        self.assertIn("ariaflow", plan)
        self.assertIn("aria2-launchd", plan)
        self.assertNotIn("ariaflow-serve-launchd", plan)
        self.assertEqual(plan["ariaflow"]["meta"]["contract"], "UCC")
        self.assertEqual(plan["ariaflow"]["result"]["observation"], "ok")
        self.assertEqual(plan["ariaflow"]["result"]["outcome"], "changed")

    def test_install_dry_run_with_web_is_describable(self) -> None:
        plan = install_all(dry_run=True, include_web=True)
        self.assertIn("ariaflow-serve-launchd", plan)
        self.assertEqual(plan["ariaflow-serve-launchd"]["result"]["reason"], "install")

    def test_lifecycle_reports_status_shape(self) -> None:
        status = status_all()
        self.assertIn("ariaflow", status)
        self.assertIn("aria2", status)
        self.assertIn("networkquality", status)
        self.assertIn("aria2-launchd", status)
        self.assertIn("ariaflow-serve-launchd", status)
        self.assertEqual(status["ariaflow"]["meta"]["contract"], "UCC")
        self.assertIn(status["ariaflow"]["result"]["outcome"], ["converged", "unchanged"])

    def test_lifecycle_status_includes_versions(self) -> None:
        with patch("aria_queue.install.package_version", return_value="9.9.9"), \
             patch("aria_queue.install.brew_is_installed", return_value=True), \
             patch("aria_queue.install.brew_package_version", side_effect=["0.1.1-alpha.21", "0.8.2"]), \
             patch("aria_queue.install.networkquality_status", return_value={"installed": True, "usable": True, "version": None, "reason": "ready", "message": "networkquality available"}), \
             patch("aria_queue.install.aria2_status", return_value={"loaded": True, "plist_exists": True, "session_exists": True, "version": "1.37.0"}), \
             patch("aria_queue.install.ariaflow_status", return_value={"loaded": True, "plist_exists": True}):
            status = status_all()
        self.assertIn("0.1.1-alpha.21", status["ariaflow"]["result"]["message"])
        self.assertIn("0.8.2", status["aria2"]["result"]["message"])
        self.assertIn("networkquality available", status["networkquality"]["result"]["message"])
        self.assertIn("1.37.0", status["aria2-launchd"]["result"]["message"])
        self.assertIn("9.9.9", status["ariaflow-serve-launchd"]["result"]["message"])

    def test_uninstall_dry_run_is_describable(self) -> None:
        plan = uninstall_all(dry_run=True)
        self.assertIn("aria2-launchd", plan)
        self.assertNotIn("ariaflow-serve-launchd", plan)
        self.assertEqual(plan["aria2-launchd"]["meta"]["contract"], "UCC")
        self.assertEqual(plan["aria2-launchd"]["result"]["reason"], "uninstall")

    def test_uninstall_dry_run_with_web_is_describable(self) -> None:
        plan = uninstall_all(dry_run=True, include_web=True)
        self.assertIn("ariaflow-serve-launchd", plan)
        self.assertEqual(plan["ariaflow-serve-launchd"]["result"]["reason"], "uninstall")


if __name__ == "__main__":
    unittest.main()
