from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aria_queue.contracts import preflight, run_ucc
from aria_queue.core import add_queue_item


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


if __name__ == "__main__":
    unittest.main()
