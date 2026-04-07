#!/usr/bin/env python3
"""Check BGS decision record for drift.

Verifies that:
- Every evidence_refs path exists and is non-empty
- Every member_version_refs commit is reachable in the respective member repo
- The BGS slice requirements match the members_used list

Exit 1 if drift detected.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_DECISION = _PROJECT / "docs" / "governance" / "bgs-decision.yaml"
_MEMBER_REPOS = {
    # All members live in the BGSPrivate monorepo (single git repo).
    "biss": _PROJECT.parent / "BGSPrivate",
    "ucc": _PROJECT.parent / "BGSPrivate",
    "uic": _PROJECT.parent / "BGSPrivate",
    "asm": _PROJECT.parent / "BGSPrivate",
    "tic": _PROJECT.parent / "BGSPrivate",
    "bgs": _PROJECT.parent / "BGSPrivate",
}

# Slice requirements: which members must appear in members_used
_SLICE_REQUIREMENTS = {
    "BGS-Classification": {"BISS"},
    "BGS-Foundation": set(),  # GIC and/or GCC
    "BGS-Execution": {"BISS", "UCC"},
    "BGS-Verified": {"BISS", "UCC", "TIC"},
    "BGS-Governed": {"BISS", "UIC", "UCC"},
    "BGS-Governed-Verified": {"BISS", "UIC", "UCC", "TIC"},
    "BGS-State-Modeled-Execution": {"BISS", "ASM", "UCC"},
    "BGS-State-Modeled-Governed": {"BISS", "ASM", "UIC", "UCC"},
    "BGS-State-Modeled-Governed-Verified": {"BISS", "ASM", "UIC", "UCC", "TIC"},
}


def _parse_yaml(text: str) -> dict:
    """Tiny YAML subset parser (handles the decision file format)."""
    result: dict = {}
    lines = text.splitlines()
    i = 0
    current_key = None
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if not line.startswith((" ", "\t", "-")):
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip("'\"")
                if val:
                    result[key] = val
                else:
                    # Block-value — collect children
                    result[key] = []
                    current_key = key
            i += 1
        elif line.lstrip().startswith("- "):
            item = line.lstrip()[2:].split("#", 1)[0].strip()
            if current_key and isinstance(result.get(current_key), list):
                result[current_key].append(item)
            i += 1
        elif ":" in stripped and current_key:
            if not isinstance(result.get(current_key), dict):
                result[current_key] = {}
            k, _, v = stripped.strip().partition(":")
            v = v.strip().split("#", 1)[0].strip().strip("'\"")
            if v:
                result[current_key][k.strip()] = v
            i += 1
        else:
            i += 1
    return result


def _check_evidence_refs(decision: dict) -> list[str]:
    """Verify every evidence_refs path exists and is non-empty."""
    errors = []
    refs = decision.get("evidence_refs", [])
    if not isinstance(refs, list):
        return ["evidence_refs is not a list"]
    decision_dir = _DECISION.parent
    for ref in refs:
        # Resolve relative to the decision file's directory, matching
        # check-bgs-compliance.py's convention.
        path = (decision_dir / ref).resolve()
        if not path.exists():
            errors.append(f"missing: {ref}")
        elif path.is_file() and path.stat().st_size == 0:
            errors.append(f"empty: {ref}")
    return errors


def _check_member_version_refs(decision: dict) -> list[str]:
    """Verify each pinned commit is reachable in the respective member repo."""
    errors = []
    refs = decision.get("member_version_refs", {})
    if not isinstance(refs, dict):
        return ["member_version_refs is not a dict"]
    for member, ref_str in refs.items():
        # ref format: "ucc@370c1f7"
        if "@" not in ref_str:
            errors.append(f"{member}: invalid ref format '{ref_str}'")
            continue
        _, commit = ref_str.split("@", 1)
        repo_path = _MEMBER_REPOS.get(member)
        if repo_path is None or not repo_path.exists():
            errors.append(f"{member}: repo not found at {repo_path}")
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", "--verify", commit + "^{commit}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                errors.append(f"{member}: commit {commit} not reachable in {repo_path}")
        except Exception as exc:
            errors.append(f"{member}: git check failed: {exc}")
    return errors


def _check_slice_requirements(decision: dict) -> list[str]:
    """Verify members_used covers the slice's required members."""
    errors = []
    slice_name = decision.get("bgs_slice", "")
    members = set(decision.get("members_used", []))
    required = _SLICE_REQUIREMENTS.get(slice_name)
    if required is None:
        errors.append(f"unknown bgs_slice: {slice_name}")
        return errors
    missing = required - members
    if missing:
        errors.append(f"slice {slice_name} missing required members: {sorted(missing)}")
    return errors


def main() -> int:
    if not _DECISION.exists():
        print(f"ERROR: {_DECISION} not found", file=sys.stderr)
        return 1
    text = _DECISION.read_text(encoding="utf-8")
    decision = _parse_yaml(text)

    all_errors: list[str] = []
    all_errors.extend(_check_slice_requirements(decision))
    all_errors.extend(_check_evidence_refs(decision))
    all_errors.extend(_check_member_version_refs(decision))

    if all_errors:
        print("BGS drift detected:", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    slice_name = decision.get("bgs_slice", "(unknown)")
    n_evidence = len(decision.get("evidence_refs", []))
    n_refs = len(decision.get("member_version_refs", {}))
    print(f"BGS clean: slice={slice_name}, {n_evidence} evidence refs, {n_refs} pinned members")
    return 0


if __name__ == "__main__":
    sys.exit(main())
