"""CLI tests — every subcommand of ariaflow-server CLI."""

from __future__ import annotations

import json
from io import StringIO
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import IsolatedTestCase

from ariaflow_server.cli import build_parser, main


class TestCliParser(unittest.TestCase):
    """Parser accepts all subcommands with correct args."""

    def test_add_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["add", "https://example.com/file.bin"])
        self.assertEqual(args.command, "add")
        self.assertEqual(args.url, "https://example.com/file.bin")
        self.assertIsNone(args.output)
        self.assertEqual(args.post_action_rule, "pending")

    def test_add_with_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "add",
                "https://example.com/file.bin",
                "--output",
                "custom.bin",
                "--post-action-rule",
                "delete",
            ]
        )
        self.assertEqual(args.output, "custom.bin")
        self.assertEqual(args.post_action_rule, "delete")

    def test_run_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run"])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.port, 6800)

    def test_run_with_port(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--port", "7800"])
        self.assertEqual(args.port, 7800)

    def test_status_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status"])
        self.assertEqual(args.command, "status")
        self.assertFalse(args.json)

    def test_status_json(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status", "--json"])
        self.assertTrue(args.json)

    def test_preflight_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["preflight"])
        self.assertEqual(args.command, "preflight")

    def test_ucc_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["ucc"])
        self.assertEqual(args.command, "ucc")
        self.assertEqual(args.port, 6800)

    def test_serve_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve"])
        self.assertEqual(args.command, "serve")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)

    def test_serve_with_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9000)

    def test_install_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install"])
        self.assertEqual(args.command, "install")
        self.assertFalse(args.dry_run)
        self.assertFalse(args.with_aria2)

    def test_install_with_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["install", "--dry-run", "--with-aria2"])
        self.assertTrue(args.dry_run)
        self.assertTrue(args.with_aria2)

    def test_uninstall_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["uninstall"])
        self.assertEqual(args.command, "uninstall")

    def test_lifecycle_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["lifecycle"])
        self.assertEqual(args.command, "lifecycle")

    def test_no_subcommand_fails(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])


class TestCliExecution(IsolatedTestCase):
    """Each subcommand executes and produces expected output."""

    def test_add_prints_queued(self) -> None:
        with patch("sys.argv", ["ariaflow-server", "add", "https://example.com/test.bin"]):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main()
        self.assertEqual(code, 0)
        self.assertIn("Queued:", stdout.getvalue())
        self.assertIn("https://example.com/test.bin", stdout.getvalue())

    def test_status_plain(self) -> None:
        # Add an item first
        with patch("sys.argv", ["ariaflow-server", "add", "https://example.com/s.bin"]):
            main()
        with patch("sys.argv", ["ariaflow-server", "status"]):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main()
        self.assertEqual(code, 0)
        self.assertIn("queued", stdout.getvalue())
        self.assertIn("https://example.com/s.bin", stdout.getvalue())

    def test_status_json(self) -> None:
        with patch("sys.argv", ["ariaflow-server", "add", "https://example.com/j.bin"]):
            main()
        with patch("sys.argv", ["ariaflow-server", "status", "--json"]):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main()
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertIn("items", data)
        self.assertGreater(len(data["items"]), 0)

    def test_preflight_plain(self) -> None:
        with (
            patch("sys.argv", ["ariaflow-server", "preflight"]),
            patch(
                "ariaflow_server.contracts.aria_rpc",
                return_value={"result": {"version": "1.37.0"}},
            ),
            patch("ariaflow_server.contracts.aria2_ensure_daemon"),
        ):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                main()
        output = stdout.getvalue()
        self.assertIn("[GATE]", output)
        self.assertIn("aria2_available", output)

    def test_preflight_json(self) -> None:
        with (
            patch("sys.argv", ["ariaflow-server", "preflight", "--json"]),
            patch(
                "ariaflow_server.contracts.aria_rpc",
                return_value={"result": {"version": "1.37.0"}},
            ),
            patch("ariaflow_server.contracts.aria2_ensure_daemon"),
        ):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                main()
        data = json.loads(stdout.getvalue())
        self.assertIn("gates", data)
        self.assertIn("status", data)

    def test_ucc_json(self) -> None:
        with (
            patch("sys.argv", ["ariaflow-server", "ucc", "--json"]),
            patch(
                "ariaflow_server.contracts.preflight",
                return_value={
                    "contract": "UCC",
                    "version": "2.0",
                    "gates": [],
                    "preferences": [],
                    "policies": [],
                    "warnings": [],
                    "hard_failures": [],
                    "status": "pass",
                    "exit_code": 0,
                },
            ),
            patch("ariaflow_server.core.process_queue", return_value=[]),
            patch("ariaflow_server.core.get_active_progress", return_value=None),
        ):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main()
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertIn("meta", data)
        self.assertIn("result", data)

    def test_install_dry_run(self) -> None:
        with patch("sys.argv", ["ariaflow-server", "install", "--dry-run"]):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main()
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertIn("ariaflow-server", data)

    def test_uninstall_dry_run(self) -> None:
        with patch("sys.argv", ["ariaflow-server", "uninstall", "--dry-run"]):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main()
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertIn("ariaflow-server", data)

    def test_lifecycle(self) -> None:
        with patch("sys.argv", ["ariaflow-server", "lifecycle"]):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                code = main()
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertIn("ariaflow-server", data)
        self.assertIn("aria2", data)


if __name__ == "__main__":
    unittest.main()
