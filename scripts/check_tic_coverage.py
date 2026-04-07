#!/usr/bin/env python3
"""Check TIC oracle coverage of the actual test suite.

The TIC oracle (`docs/governance/tic-oracle.md`) is a hand-curated table
of every test name with its intent, oracle, and trace target. Whenever a
new test is added, the oracle must register it; otherwise the BGS
verification claim is incomplete (TIC declares that all tests have
explicit trace targets).

This script compares the live pytest collection against the test names
registered in the oracle and reports drift in both directions:

- ``missing`` — tests that exist but are not in the oracle
- ``stale``  — oracle entries that reference tests no longer in the suite

Reports drift to stderr but **does not exit non-zero**. The current
oracle has a known historical gap that predates this checker; once that
gap is closed, the script can be flipped to enforcing by removing the
``ALWAYS_PASS`` flag below.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_TIC_ORACLE = _PROJECT / "docs" / "governance" / "tic-oracle.md"

# Set to False once every test in the suite has an oracle entry; the
# script will then fail check-drift on any new uncovered test.
ALWAYS_PASS = True


def _collect_tests() -> set[str]:
    """Return the set of test method names pytest would run."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
        capture_output=True,
        text=True,
        cwd=_PROJECT,
    )
    tests: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        # Format: tests/test_x.py::TestClass::test_name
        # or:     tests/test_x.py::test_name
        tests.add(line.split("::")[-1])
    return tests


def _registered_tests() -> set[str]:
    """Return the set of test names referenced in tic-oracle.md.

    Accepts both bare ``test_name`` and ``ClassName::test_name`` forms
    inside backticks, since the oracle uses the qualified form for some
    parameter-table sections (e.g. the aria2 RPC wrapper inventory).
    """
    text = _TIC_ORACLE.read_text(encoding="utf-8")
    return set(re.findall(r"`(?:\w+::)?(test_\w+)`", text))


def main() -> int:
    if not _TIC_ORACLE.exists():
        print(f"ERROR: {_TIC_ORACLE} not found", file=sys.stderr)
        return 1

    actual = _collect_tests()
    registered = _registered_tests()
    if not actual:
        print("ERROR: pytest collected no tests", file=sys.stderr)
        return 1

    missing = sorted(actual - registered)
    stale = sorted(registered - actual)
    covered = len(actual & registered)

    print(
        f"TIC oracle coverage: {covered}/{len(actual)} tests registered "
        f"({len(missing)} missing, {len(stale)} stale)"
    )

    if missing:
        print(f"\n{len(missing)} test(s) in suite but not in tic-oracle.md:")
        for name in missing[:20]:
            print(f"  - {name}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")

    if stale:
        print(
            f"\n{len(stale)} oracle entry(ies) reference tests not in the suite:",
            file=sys.stderr,
        )
        for name in stale:
            print(f"  - {name}", file=sys.stderr)

    if (missing or stale) and not ALWAYS_PASS:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
