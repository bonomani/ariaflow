#!/usr/bin/env python3
"""Check openapi.yaml for breaking changes against a git baseline.

Reports:
- Removed endpoints (BREAKING)
- Removed response fields (BREAKING)
- Added endpoints (informational)
- Added response fields (informational)

Usage: python scripts/check_api_surface.py [BASE_REV]
Default BASE_REV: HEAD~1

Exit 1 on breaking changes.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_SPEC = "src/ariaflow_server/openapi.yaml"


def _load_baseline(rev: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(_PROJECT), "show", f"{rev}:{_SPEC}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"Cannot read {_SPEC} at {rev}: {result.stderr.strip()}")
    return result.stdout


def _load_current() -> str:
    return (_PROJECT / _SPEC).read_text(encoding="utf-8")


def _parse_endpoints(yaml_text: str) -> dict[str, set[str]]:
    """Return {path: {methods}} from the paths: section."""
    endpoints: dict[str, set[str]] = {}
    in_paths = False
    current_path: str | None = None
    for line in yaml_text.splitlines():
        if line.startswith("paths:"):
            in_paths = True
            continue
        if in_paths and line and not line[0].isspace():
            break
        if not in_paths:
            continue
        m = re.match(r"^ {2}(/\S+):\s*$", line)
        if m:
            current_path = m.group(1)
            endpoints.setdefault(current_path, set())
            continue
        m = re.match(r"^ {4}(get|post|put|patch|delete):\s*$", line)
        if m and current_path:
            endpoints[current_path].add(m.group(1))
    return endpoints


def _parse_response_fields(yaml_text: str) -> dict[str, set[str]]:
    """Return {endpoint: {field_names}} from 200 response schemas."""
    fields: dict[str, set[str]] = {}
    lines = yaml_text.splitlines()
    i = 0
    current_endpoint: str | None = None
    current_method: str | None = None
    in_properties = False
    prop_indent = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^ {2}(/\S+):\s*$", line)
        if m:
            current_endpoint = m.group(1)
            current_method = None
            in_properties = False
            i += 1
            continue
        m = re.match(r"^ {4}(get|post|put|patch|delete):\s*$", line)
        if m and current_endpoint:
            current_method = m.group(1)
            in_properties = False
            i += 1
            continue
        if current_endpoint and current_method:
            # Look for: properties: under 200 response
            if re.match(r"^\s{16}properties:\s*$", line):
                in_properties = True
                prop_indent = 18
                key = f"{current_method.upper()} {current_endpoint}"
                fields.setdefault(key, set())
                i += 1
                continue
            if in_properties:
                m = re.match(r"^ {18}(\w+):\s*$", line)
                if m:
                    key = f"{current_method.upper()} {current_endpoint}"
                    fields.setdefault(key, set()).add(m.group(1))
                elif line.strip() and not line.startswith(" " * prop_indent):
                    in_properties = False
        i += 1
    return fields


def main() -> int:
    base_rev = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"

    try:
        baseline_text = _load_baseline(base_rev)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1

    current_text = _load_current()

    baseline_eps = _parse_endpoints(baseline_text)
    current_eps = _parse_endpoints(current_text)
    baseline_fields = _parse_response_fields(baseline_text)
    current_fields = _parse_response_fields(current_text)

    # Flatten endpoints to "METHOD path"
    def flatten(eps: dict[str, set[str]]) -> set[str]:
        return {f"{m.upper()} {p}" for p, methods in eps.items() for m in methods}

    baseline_set = flatten(baseline_eps)
    current_set = flatten(current_eps)

    removed_endpoints = sorted(baseline_set - current_set)
    added_endpoints = sorted(current_set - baseline_set)

    removed_fields: list[tuple[str, str]] = []
    added_fields: list[tuple[str, str]] = []
    for key in sorted(set(baseline_fields) | set(current_fields)):
        old = baseline_fields.get(key, set())
        new = current_fields.get(key, set())
        for f in sorted(old - new):
            removed_fields.append((key, f))
        for f in sorted(new - old):
            added_fields.append((key, f))

    print(f"API surface diff: {base_rev} → HEAD")
    print(f"  baseline: {len(baseline_set)} endpoints, {sum(len(v) for v in baseline_fields.values())} response fields")
    print(f"  current:  {len(current_set)} endpoints, {sum(len(v) for v in current_fields.values())} response fields")

    if removed_endpoints:
        print(f"\n  BREAKING — removed endpoints ({len(removed_endpoints)}):")
        for ep in removed_endpoints:
            print(f"    - {ep}")
    if removed_fields:
        print(f"\n  BREAKING — removed response fields ({len(removed_fields)}):")
        for ep, f in removed_fields:
            print(f"    - {ep}: {f}")
    if added_endpoints:
        print(f"\n  added endpoints ({len(added_endpoints)}):")
        for ep in added_endpoints:
            print(f"    + {ep}")
    if added_fields:
        print(f"\n  added response fields ({len(added_fields)}):")
        for ep, f in added_fields:
            print(f"    + {ep}: {f}")

    if removed_endpoints or removed_fields:
        print("\nBREAKING changes detected", file=sys.stderr)
        return 1
    print("\nNo breaking changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
