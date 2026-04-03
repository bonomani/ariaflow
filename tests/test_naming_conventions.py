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
- No aria_ prefix (must be aria2_)
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class TestNamingConventions(unittest.TestCase):
    def test_all_identifiers_follow_naming_rules(self) -> None:
        """Run gen_all_variables.py --check and assert zero violations."""
        script = Path(__file__).resolve().parents[1] / "scripts" / "gen_all_variables.py"
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


if __name__ == "__main__":
    unittest.main()
