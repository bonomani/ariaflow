"""Test naming conventions across the codebase.

Enforces:
- Item fields: snake_case
- State fields: snake_case
- Constants: UPPER_SNAKE_CASE
- Classes: PascalCase
- Public functions: snake_case
- Private functions: _snake_case
- Public aria2 functions: aria2_ prefix
- Private aria2 functions: _aria2_ prefix
- No aria_ prefix (must be aria2_, exception: aria_rpc)
- Status values: lowercase only
- Module names: snake_case
- API response keys: snake_case only (no camelCase leaking from aria2)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT / "src" / "aria_queue"

sys.path.insert(0, str(_PROJECT / "src"))


class TestIdentifierNaming(unittest.TestCase):
    """Run gen_all_variables.py --check for identifier naming rules."""

    def test_all_identifiers_follow_naming_rules(self) -> None:
        script = _PROJECT / "scripts" / "gen_all_variables.py"
        result = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"Naming convention violations:\n{result.stdout}{result.stderr}",
        )


class TestModuleNaming(unittest.TestCase):
    """Module filenames must be snake_case."""

    def test_module_names_are_snake_case(self) -> None:
        violations: list[str] = []
        for root, dirs, files in os.walk(_SRC):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py"):
                    continue
                name = f.removesuffix(".py")
                if name.startswith("__"):
                    continue
                if not re.match(r"^[a-z][a-z0-9_]*$", name):
                    violations.append(f"{os.path.join(root, f)}: {name}")
        self.assertEqual(violations, [], f"Module names not snake_case:\n" + "\n".join(violations))


class TestStatusValues(unittest.TestCase):
    """Status values in ITEM_STATUSES must be lowercase."""

    def test_item_statuses_are_lowercase(self) -> None:
        from aria_queue.queue_ops import ITEM_STATUSES

        for status in ITEM_STATUSES:
            self.assertEqual(
                status,
                status.lower(),
                f"Status '{status}' is not lowercase",
            )
            self.assertRegex(
                status,
                r"^[a-z][a-z_]*$",
                f"Status '{status}' contains invalid characters",
            )


class TestApiResponseKeys(unittest.TestCase):
    """API response keys must be snake_case — no camelCase leaking from aria2.

    Checks queue item dicts and state dicts for camelCase keys.
    """

    _CAMEL_CASE = re.compile(r"^[a-z]+[A-Z]")

    def _check_keys(self, obj: object, path: str = "") -> list[str]:
        violations: list[str] = []
        if isinstance(obj, dict):
            for key in obj:
                if isinstance(key, str) and self._CAMEL_CASE.match(key):
                    # Exception: _rev is not camelCase
                    violations.append(f"{path}.{key}" if path else key)
                violations.extend(self._check_keys(obj[key], f"{path}.{key}" if path else key))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                violations.extend(self._check_keys(item, f"{path}[{i}]"))
        return violations

    def test_queue_item_keys_are_snake_case(self) -> None:
        """Build a queue item via add_queue_item and check all keys."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ARIA_QUEUE_DIR"] = tmpdir
            try:
                from aria_queue.queue_ops import add_queue_item, load_queue
                from importlib import reload
                import aria_queue.storage as storage_mod
                reload(storage_mod)

                add_queue_item("https://example.com/test.bin")
                items = load_queue()
                self.assertTrue(len(items) > 0, "No items in queue")
                violations = self._check_keys(items[0])
                self.assertEqual(
                    violations,
                    [],
                    f"camelCase keys in queue item:\n" + "\n".join(violations),
                )
            finally:
                os.environ.pop("ARIA_QUEUE_DIR", None)

    def test_state_keys_are_snake_case(self) -> None:
        """Load default state and check all keys."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["ARIA_QUEUE_DIR"] = tmpdir
            try:
                from aria_queue.state import load_state
                from importlib import reload
                import aria_queue.storage as storage_mod
                reload(storage_mod)

                state = load_state()
                violations = self._check_keys(state)
                self.assertEqual(
                    violations,
                    [],
                    f"camelCase keys in state:\n" + "\n".join(violations),
                )
            finally:
                os.environ.pop("ARIA_QUEUE_DIR", None)


class TestTestNaming(unittest.TestCase):
    """Test function names must start with test_ and be snake_case."""

    def test_test_names_are_snake_case(self) -> None:
        violations: list[str] = []
        tests_dir = _PROJECT / "tests"
        for f in tests_dir.rglob("test_*.py"):
            try:
                import ast
                tree = ast.parse(f.read_text())
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                    if not re.match(r"^test_[a-z0-9_]+$", node.name):
                        violations.append(f"{f.name}:{node.lineno}: {node.name}")
        self.assertEqual(
            violations,
            [],
            f"Test names not snake_case:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
