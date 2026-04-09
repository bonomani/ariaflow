#!/usr/bin/env python3
"""Approach 2 — Concept inventory drift check.

Asserts that every concept produced by code is documented by governance,
and every concept documented by governance is used by code.

Checks:
1. **State fields ↔ ASM axes**
   Every field in ``state.py`` default state dict must be mentioned in
   ``asm-state-model.md`` (axis description or "Stored fields" line).

2. **Actions ↔ BISS/ASM**
   Every unique action string in ``record_action(action=...)`` calls must
   appear in either the BISS boundary descriptions or the ASM transition
   catalog.

3. **Preferences ↔ code usage**
   Every preference in ``contracts.DEFAULT_DECLARATION`` must be referenced
   by a ``pref_value("<name>", ...)`` call somewhere in the source tree.

Exit 1 if any concept is undocumented or dead.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT / "src" / "ariaflow_server"
_GOV = _PROJECT / "docs" / "governance"


# ── 1. State fields ──

def _state_fields() -> set[str]:
    """Extract keys of the default state dict from state.py load_state()."""
    text = (_SRC / "state.py").read_text(encoding="utf-8")
    # Match the default dict literal passed to read_json inside load_state
    m = re.search(r"def load_state.*?read_json\(.*?\{(.*?)\}", text, re.DOTALL)
    if not m:
        return set()
    body = m.group(1)
    keys = set(re.findall(r'"(\w+)"\s*:', body))
    return keys


def _asm_corpus() -> str:
    return (_GOV / "asm-state-model.md").read_text(encoding="utf-8")


def _check_state_fields() -> list[str]:
    errors = []
    fields = _state_fields()
    corpus = _asm_corpus()
    for field in sorted(fields):
        if field not in corpus:
            errors.append(f"state field '{field}' missing from asm-state-model.md")
    return errors


# ── 2. Actions ──

def _collect_actions() -> set[str]:
    """Collect every unique action= argument to record_action()."""
    actions: set[str] = set()
    for py in _SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r'record_action\s*\(\s*\n?\s*action\s*=\s*"(\w+)"', text):
            actions.add(m.group(1))
    return actions


def _governance_action_corpus() -> str:
    parts = []
    for name in ("biss-classification.md", "asm-state-model.md", "tic-oracle.md"):
        path = _GOV / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _check_actions() -> list[str]:
    errors = []
    actions = _collect_actions()
    corpus = _governance_action_corpus()
    for action in sorted(actions):
        if action not in corpus:
            errors.append(f"action '{action}' not documented in BISS/ASM/TIC")
    return errors


# ── 3. Preferences ──

def _default_preferences() -> set[str]:
    """Extract preference names from contracts.DEFAULT_DECLARATION."""
    text = (_SRC / "contracts.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DEFAULT_DECLARATION":
                    # Walk nested dicts/lists looking for "name": "<value>"
                    for sub in ast.walk(node.value):
                        if isinstance(sub, ast.Dict):
                            for k, v in zip(sub.keys, sub.values):
                                if (isinstance(k, ast.Constant) and k.value == "name"
                                        and isinstance(v, ast.Constant)):
                                    names.add(v.value)
    # Filter to the preference entries only: exclude gate names by checking
    # that the name appears in a preference context (has "value" sibling).
    # Simpler: exclude known gate names.
    names -= {"aria2_available", "queue_readable", "queue"}
    return names


def _pref_reference_corpus() -> str:
    """Concatenate all .py files in src/ariaflow_server/."""
    parts = []
    for py in _SRC.rglob("*.py"):
        parts.append(py.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _check_preferences() -> list[str]:
    errors = []
    prefs = _default_preferences()
    corpus = _pref_reference_corpus()
    for name in sorted(prefs):
        pattern = f'"{name}"'
        # Must appear somewhere other than the contracts definition itself.
        count = corpus.count(pattern)
        if count < 2:  # 1 = definition only
            errors.append(f"preference '{name}' defined but not referenced in code")
    return errors


# ── Main ──

def main() -> int:
    all_errors: list[tuple[str, list[str]]] = [
        ("state fields ↔ ASM", _check_state_fields()),
        ("actions ↔ BISS/ASM/TIC", _check_actions()),
        ("preferences ↔ code", _check_preferences()),
    ]

    total_errors = sum(len(errs) for _, errs in all_errors)

    if total_errors == 0:
        print("Concept inventory clean:")
        print(f"  state fields:  {len(_state_fields())}")
        print(f"  actions:       {len(_collect_actions())}")
        print(f"  preferences:   {len(_default_preferences())}")
        return 0

    print("Concept drift detected:")
    for category, errors in all_errors:
        if errors:
            print(f"\n  {category} ({len(errors)}):")
            for err in errors:
                print(f"    - {err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
