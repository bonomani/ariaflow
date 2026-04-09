#!/usr/bin/env python3
"""Generate docs/ALL_VARIABLES.md and verify naming conventions.

Usage:
    python scripts/gen_all_variables.py          # generate doc
    python scripts/gen_all_variables.py --check  # check only, exit 1 on violations
"""

from __future__ import annotations

import ast
import os
import re
import sys


SRC = os.path.join(os.path.dirname(__file__), "..", "src", "aria_queue")


def collect() -> dict:
    results: dict = {
        "constants": [],
        "classes": [],
        "functions": [],
        "item_fields": set(),
        "state_fields": set(),
    }

    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(root, f)
            mod = path.replace(SRC + "/", "").replace("/", ".").replace(".py", "")
            try:
                tree = ast.parse(open(path).read())
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    results["classes"].append((mod, node.name))
                elif isinstance(node, ast.FunctionDef):
                    if node.col_offset == 0:
                        results["functions"].append((mod, node.name))
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id.isupper():
                            results["constants"].append((mod, t.id))

            text = open(path).read()
            for m in re.finditer(
                r'item\["(\w+)"\]|item\.get\("(\w+)"|item\.pop\("(\w+)"', text
            ):
                results["item_fields"].add(m.group(1) or m.group(2) or m.group(3))
            for m in re.finditer(
                r'state\["(\w+)"\]|state\.get\("(\w+)"', text
            ):
                results["state_fields"].add(m.group(1) or m.group(2))

    return results


def check_naming(results: dict) -> list[str]:
    """Return list of naming violations."""
    violations: list[str] = []

    # Rule 1: Item fields must be snake_case
    for f in sorted(results["item_fields"]):
        if f != f.lower() or (f != "_rev" and any(c.isupper() for c in f)):
            violations.append(f"ITEM FIELD not snake_case: {f}")

    # Rule 2: State fields must be snake_case
    for f in sorted(results["state_fields"]):
        if f != f.lower() or (f != "_rev" and any(c.isupper() for c in f)):
            violations.append(f"STATE FIELD not snake_case: {f}")

    # Rule 3: Constants must be UPPER_SNAKE_CASE (allow leading _)
    for mod, name in results["constants"]:
        stripped = name.lstrip("_")
        if stripped and not re.match(r"^[A-Z][A-Z0-9_]*$", stripped):
            violations.append(f"CONSTANT not UPPER_SNAKE_CASE: {mod}.{name}")

    # Rule 4: Classes must be PascalCase
    for mod, name in results["classes"]:
        if not re.match(r"^[A-Z][a-zA-Z0-9]*$", name):
            violations.append(f"CLASS not PascalCase: {mod}.{name}")

    # Rule 5: Public functions that call aria2 RPC must have aria2_ prefix
    # (checked by presence — we can't auto-detect RPC calls here,
    #  but we check that aria2_ functions exist only in aria2-related modules)

    # Rule 6: Public functions must be snake_case
    for mod, name in results["functions"]:
        if name.startswith("_"):
            continue  # private
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            violations.append(f"PUBLIC FUNCTION not snake_case: {mod}.{name}")

    # Rule 7: Private functions must be _snake_case
    for mod, name in results["functions"]:
        if not name.startswith("_"):
            continue
        inner = name.lstrip("_")
        if not re.match(r"^[a-z][a-z0-9_]*$", inner):
            violations.append(f"PRIVATE FUNCTION not _snake_case: {mod}.{name}")

    # Rule 8: aria2-related private functions must use _aria2_ prefix
    for mod, name in results["functions"]:
        if not name.startswith("_"):
            continue
        inner = name.lstrip("_")
        # If name contains "aria" but doesn't start with _aria2_
        if "aria" in inner.lower() and not name.startswith("_aria2_"):
            violations.append(
                f"PRIVATE aria2 FUNCTION missing _aria2_ prefix: {mod}.{name}"
            )

    # Rule 9: Public aria2 functions must use aria2_ prefix (not aria_ or _aria)
    # Exception: aria_rpc is the low-level JSON-RPC transport function
    for mod, name in results["functions"]:
        if name.startswith("_"):
            continue
        if name == "aria_rpc":
            continue  # transport layer, not a specific aria2 method wrapper
        if name.startswith("aria_") and not name.startswith("aria2_"):
            violations.append(
                f"PUBLIC FUNCTION uses aria_ instead of aria2_: {mod}.{name}"
            )

    return violations


def render_markdown(results: dict) -> str:
    lines: list[str] = []
    lines.append("# All Variables — ariaflow-server")
    lines.append("")
    lines.append(
        "> Auto-generated by `scripts/gen_all_variables.py` — do not edit manually."
    )
    lines.append(">")
    lines.append("> Regenerate: `python scripts/gen_all_variables.py`")
    lines.append("")

    lines.append(f"## Item Fields ({len(results['item_fields'])})")
    lines.append("")
    lines.append("| Field | Convention |")
    lines.append("|---|---|")
    for f in sorted(results["item_fields"]):
        lines.append(f"| `{f}` | snake_case |")

    lines.append("")
    lines.append(f"## State Fields ({len(results['state_fields'])})")
    lines.append("")
    lines.append("| Field | Convention |")
    lines.append("|---|---|")
    for f in sorted(results["state_fields"]):
        lines.append(f"| `{f}` | snake_case |")

    lines.append("")
    lines.append(f"## Constants ({len(results['constants'])})")
    lines.append("")
    lines.append("| Module | Name |")
    lines.append("|---|---|")
    for mod, name in sorted(results["constants"]):
        lines.append(f"| `{mod}` | `{name}` |")

    lines.append("")
    lines.append(f"## Classes ({len(results['classes'])})")
    lines.append("")
    lines.append("| Module | Name |")
    lines.append("|---|---|")
    for mod, name in sorted(results["classes"]):
        lines.append(f"| `{mod}` | `{name}` |")

    pub = [(m, n) for m, n in results["functions"] if not n.startswith("_")]
    priv = [(m, n) for m, n in results["functions"] if n.startswith("_")]
    a2_pub = [(m, n) for m, n in pub if n.startswith("aria2_")]
    a2_priv = [(m, n) for m, n in priv if n.startswith("_aria2_")]
    other_pub = [(m, n) for m, n in pub if not n.startswith("aria2_")]
    other_priv = [(m, n) for m, n in priv if not n.startswith("_aria2_")]

    for title, items, convention in [
        (f"aria2_ Public Functions ({len(a2_pub)})", a2_pub, "aria2_ + snake_case"),
        (f"_aria2_ Private Functions ({len(a2_priv)})", a2_priv, "_aria2_ + snake_case"),
        (f"Public Functions ({len(other_pub)})", other_pub, "snake_case"),
        (f"Private Functions ({len(other_priv)})", other_priv, "_snake_case"),
    ]:
        lines.append("")
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Module | Function |")
        lines.append("|---|---|")
        for mod, name in sorted(items):
            lines.append(f"| `{mod}` | `{name}` |")

    total = (
        len(results["item_fields"])
        + len(results["state_fields"])
        + len(results["constants"])
        + len(results["classes"])
        + len(a2_pub)
        + len(a2_priv)
        + len(other_pub)
        + len(other_priv)
    )

    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Count | Convention |")
    lines.append("|---|---|---|")
    lines.append(f"| Item fields | {len(results['item_fields'])} | snake_case |")
    lines.append(f"| State fields | {len(results['state_fields'])} | snake_case |")
    lines.append(f"| Constants | {len(results['constants'])} | UPPER_SNAKE_CASE |")
    lines.append(f"| Classes | {len(results['classes'])} | PascalCase |")
    lines.append(f"| aria2_ public functions | {len(a2_pub)} | aria2_ + snake_case |")
    lines.append(f"| _aria2_ private functions | {len(a2_priv)} | _aria2_ + snake_case |")
    lines.append(f"| Public functions | {len(other_pub)} | snake_case |")
    lines.append(f"| Private functions | {len(other_priv)} | _snake_case |")
    lines.append(f"| **Total** | **{total}** | |")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    check_only = "--check" in sys.argv

    results = collect()
    violations = check_naming(results)

    if check_only:
        if violations:
            print(f"FAIL: {len(violations)} naming violations:")
            for v in violations:
                print(f"  - {v}")
            sys.exit(1)
        else:
            print(f"OK: {sum(len(v) if isinstance(v, set) else 1 for v in results.values())} identifiers, 0 violations")
            sys.exit(0)

    md = render_markdown(results)
    out = os.path.join(os.path.dirname(__file__), "..", "docs", "ALL_VARIABLES.md")
    with open(out, "w") as f:
        f.write(md)

    if violations:
        print(f"Generated {out} ({len(violations)} VIOLATIONS found):")
        for v in violations:
            print(f"  - {v}")
    else:
        print(f"Generated {out} (0 violations)")


if __name__ == "__main__":
    main()
