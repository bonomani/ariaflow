#!/usr/bin/env python3
"""Check saved declaration.json for drift against contract defaults.

Reports:
- Preferences in code but missing from user's declaration (new, need upgrade)
- Preferences in user's declaration but not in code (stale, should remove)
- Preferences with user values differing from defaults (informational)

Exit 1 only on schema mismatch (new/removed keys), not on value divergence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT / "src"))


def main() -> int:
    from aria_queue.contracts import DEFAULT_DECLARATION, declaration_path

    path = declaration_path()
    if not path.exists():
        print(f"No declaration at {path} — nothing to check (will use defaults at first run)")
        return 0

    try:
        user_decl = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: cannot parse {path}: {exc}", file=sys.stderr)
        return 1

    default_prefs = {
        p["name"]: p
        for p in DEFAULT_DECLARATION.get("uic", {}).get("preferences", [])
    }
    user_prefs = {
        p["name"]: p
        for p in user_decl.get("uic", {}).get("preferences", [])
    }

    new_in_code = sorted(set(default_prefs) - set(user_prefs))
    stale_in_user = sorted(set(user_prefs) - set(default_prefs))
    value_diffs = []
    for name in sorted(set(default_prefs) & set(user_prefs)):
        default_val = default_prefs[name].get("value")
        user_val = user_prefs[name].get("value")
        if default_val != user_val:
            value_diffs.append((name, default_val, user_val))

    schema_drift = bool(new_in_code or stale_in_user)

    print(f"Declaration: {path}")
    print(f"  code defaults: {len(default_prefs)} preferences")
    print(f"  user values:   {len(user_prefs)} preferences")

    if new_in_code:
        print(f"\n  NEW in code, missing from user declaration ({len(new_in_code)}):")
        for name in new_in_code:
            default = default_prefs[name].get("value")
            print(f"    + {name} (default: {default!r})")

    if stale_in_user:
        print(f"\n  STALE in user declaration, not in code ({len(stale_in_user)}):")
        for name in stale_in_user:
            print(f"    - {name}")

    if value_diffs:
        print(f"\n  user values differ from defaults ({len(value_diffs)}):")
        for name, default_val, user_val in value_diffs:
            print(f"    ~ {name}: default={default_val!r}, user={user_val!r}")

    if schema_drift:
        print("\nSchema drift — declaration needs upgrade", file=sys.stderr)
        return 1
    print("\nSchema matches. Value divergences are informational.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
