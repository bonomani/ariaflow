from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aria_queue.contracts import preflight, run_ucc
from aria_queue.core import add_queue_item, load_action_log
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
        log = load_action_log()
        add_entry = next(entry for entry in reversed(log) if entry.get("action") == "add")
        self.assertIn("observed_before", add_entry)
        self.assertIn("observed_after", add_entry)

    def test_preflight_emits_gate_results(self) -> None:
        result = preflight()
        self.assertIn("gates", result)
        self.assertIn("status", result)
        self.assertIn(result["exit_code"], [0, 1])

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
        self.assertIn("aria2-launchd", status)
        self.assertIn("ariaflow-serve-launchd", status)
        self.assertEqual(status["ariaflow"]["meta"]["contract"], "UCC")
        self.assertIn(status["ariaflow"]["result"]["outcome"], ["converged", "unchanged"])

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
