#!/usr/bin/env python3
"""Check that ``docs/SPEC.md`` is up to date with the source artifacts.

Regenerates the SPEC into memory via ``gen_spec.render()`` and diffs it
against the committed file. Exit non-zero on drift so ``make verify``
catches forgotten regenerations.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "scripts"))

from gen_spec import _OUTPUT, render  # noqa: E402


def main() -> int:
    expected = render()
    if not _OUTPUT.exists():
        print(f"FAIL: {_OUTPUT.relative_to(_PROJECT)} does not exist", file=sys.stderr)
        print("Run: python scripts/gen_spec.py", file=sys.stderr)
        return 1
    actual = _OUTPUT.read_text(encoding="utf-8")
    if actual == expected:
        print("SPEC.md clean")
        return 0
    diff = list(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile="committed",
            tofile="regenerated",
            n=2,
        )
    )
    print(
        f"FAIL: {_OUTPUT.relative_to(_PROJECT)} is stale "
        f"({sum(1 for line in diff if line.startswith('+ ') or line.startswith('- '))} line changes)",
        file=sys.stderr,
    )
    sys.stderr.writelines(diff[:60])
    if len(diff) > 60:
        print(f"... ({len(diff) - 60} more lines)", file=sys.stderr)
    print("\nRun: python scripts/gen_spec.py", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
