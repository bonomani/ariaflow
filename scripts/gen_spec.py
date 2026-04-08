#!/usr/bin/env python3
"""Generate ``docs/SPEC.md`` from the live code + governance artifacts.

The SPEC is the **reverse-engineered current state of the project**.
Re-run after any change. The only hand-maintained input is
``docs/GOAL.md``; everything else is derived from:

- ``pyproject.toml``                              (identity)
- ``src/aria_queue/__init__.py``                  (live version)
- ``src/aria_queue/webapp.py``                    (HTTP dispatch tables)
- ``src/aria_queue/openapi_schemas.py``           (response shapes)
- ``src/aria_queue/contracts.py``                 (UIC declaration)
- ``src/aria_queue/queue_ops.py``                 (QueueItem dataclass)
- ``src/aria_queue/aria2_rpc.py``                 (aria2 wrappers)
- ``docs/governance/biss-classification.md``      (boundaries / actions)
- ``docs/governance/asm-state-model.md``          (state model)
- ``docs/governance/BGS.md``                      (BGS claim)
- ``docs/governance/bgs-decision.yaml``           (decision record)
- live ``pytest --collect-only``                  (test count)

Wired into ``check-drift`` via ``scripts/check_spec.py`` so SPEC drift
fails ``make verify``.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT / "src"
sys.path.insert(0, str(_SRC))

_OUTPUT = _PROJECT / "docs" / "SPEC.md"


# ── helpers ──────────────────────────────────────────────────────────


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(_PROJECT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "(unknown)"


def _git_commit_date() -> str:
    """Return the HEAD commit date — stable across reruns of the same commit."""
    try:
        result = subprocess.run(
            ["git", "-C", str(_PROJECT), "show", "-s", "--format=%cs", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "(unknown)"


def _extract_section(md: str, heading: str) -> str:
    """Return the body of a markdown section under the given H2/H1.

    Tolerates an optional ``N. `` numeric prefix on the heading
    (e.g. ``## 4. Coherence Rules``) so callers can ask by name only.
    """
    pattern = rf"^#+\s*(?:\d+\.\s*)?{re.escape(heading)}\s*\n(.*?)(?=\n#+\s|\Z)"
    m = re.search(pattern, md, re.MULTILINE | re.DOTALL)
    return (m.group(1).strip() if m else "").strip()


# ── section builders ────────────────────────────────────────────────


def section_goal() -> str:
    goal = _read(_PROJECT / "docs" / "GOAL.md")
    # Strip the file's own H1 — we add our own numbered heading.
    body = re.sub(r"^#\s+.*\n+", "", goal, count=1)
    # Drop the trailing "How this file is used" block — meta, not content.
    body = re.sub(r"\n##\s+How this file is used.*\Z", "", body, flags=re.DOTALL)
    # Demote remaining H2s to H3 so they nest under our "## 1. Goal".
    body = re.sub(r"^##\s", "### ", body, flags=re.MULTILINE)
    return f"## 1. Goal\n\n{body.strip()}\n"


def section_identity() -> str:
    pyproject = _read(_PROJECT / "pyproject.toml")
    name = re.search(r'^name\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    py_req = re.search(r'^requires-python\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    deps = re.search(
        r"^dependencies\s*=\s*\[(.*?)\]", pyproject, re.MULTILINE | re.DOTALL
    )
    dep_list = []
    if deps:
        for line in deps.group(1).splitlines():
            line = line.strip().strip(",").strip('"')
            if line and not line.startswith("#"):
                dep_list.append(line)

    from aria_queue import __version__

    lines = ["## 2. Identity", ""]
    lines.append(f"- **Name:** `{name.group(1) if name else 'aria-queue'}`")
    lines.append(
        f"- **Version:** `{__version__}` (live from `src/aria_queue/__init__.py`)"
    )
    lines.append(f"- **Python:** `{py_req.group(1) if py_req else '?'}`")
    if dep_list:
        lines.append(
            f"- **Runtime dependencies:** {', '.join(f'`{d}`' for d in dep_list)}"
        )
    else:
        lines.append("- **Runtime dependencies:** _none_ (zero-dependency)")
    return "\n".join(lines) + "\n"


def section_architecture() -> str:
    arch = _read(_PROJECT / "docs" / "ARCHITECTURE.md")
    overview = _extract_section(arch, "Overview")
    concepts = _extract_section(arch, "Core Concepts")
    relationships = _extract_section(arch, "Relationships")
    out = ["## 3. Architecture", ""]
    if overview:
        out.append(overview)
        out.append("")
    if concepts:
        out.append("### Core concepts")
        out.append("")
        out.append(concepts)
        out.append("")
    if relationships:
        out.append("### Relationships")
        out.append("")
        out.append(relationships)
        out.append("")
    return "\n".join(out)


def section_asm() -> str:
    asm = _read(_PROJECT / "docs" / "governance" / "asm-state-model.md")
    out = ["## 4. State Model (ASM)", ""]
    for heading in (
        "State Axes",
        "Derived States",
        "Transition Catalog",
        "Coherence Rules",
    ):
        body = _extract_section(asm, heading)
        if body:
            out.append(f"### {heading}")
            out.append("")
            out.append(body)
            out.append("")
    return "\n".join(out)


def section_biss() -> str:
    biss = _read(_PROJECT / "docs" / "governance" / "biss-classification.md")
    out = ["## 5. Boundaries (BISS)", ""]
    for heading in ("Boundary Inventory", "Interaction Classes", "Action Catalog"):
        body = _extract_section(biss, heading)
        if body:
            out.append(f"### {heading}")
            out.append("")
            out.append(body)
            out.append("")
    return "\n".join(out)


def _parse_dispatch_table(name: str) -> list[tuple[str, str]]:
    """Return [(path, handler), ...] for a dispatch dict by name."""
    text = _read(_PROJECT / "src" / "aria_queue" / "webapp.py")
    pattern = rf"{name}\s*=\s*\{{(.*?)\n    \}}"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return []
    entries = re.findall(r'"([^"]+)"\s*:\s*routes\.(\w+)', m.group(1))
    return entries


def section_http_api() -> str:
    from aria_queue.openapi_schemas import RESPONSE_SCHEMAS

    gets = _parse_dispatch_table("_GET_ROUTES")
    posts = _parse_dispatch_table("_POST_ROUTES")
    out = ["## 6. HTTP API surface", ""]
    out.append(
        f"**{len(gets)} GET + {len(posts)} POST endpoints** dispatched from `webapp._GET_ROUTES` / `_POST_ROUTES`."
    )
    out.append("")

    def _emit(method: str, table: list[tuple[str, str]]) -> None:
        out.append(f"### {method} endpoints ({len(table)})")
        out.append("")
        out.append("| Path | Handler | Schema |")
        out.append("|---|---|---|")
        for path, handler in sorted(table):
            schema_key = f"{method} {path}"
            schema_marker = "✓ typed" if schema_key in RESPONSE_SCHEMAS else "—"
            out.append(f"| `{path}` | `routes.{handler}` | {schema_marker} |")
        out.append("")

    _emit("GET", gets)
    _emit("POST", posts)
    out.append(
        "Schemas marked **✓ typed** appear in `src/aria_queue/openapi_schemas.py::RESPONSE_SCHEMAS` "
        "and are emitted into `src/aria_queue/openapi.yaml` by `scripts/gen_openapi.py`. "
        "Tests in `TestOpenapiSchemas` (test_unit.py) pin every typed schema against the live response shape."
    )
    out.append("")
    return "\n".join(out)


def _ast_aria2_functions() -> tuple[list[str], list[str]]:
    """Return (rpc_wrappers, helpers) by inspecting aria2_rpc.py source.

    A "wrapper" is a `def aria2_*` function whose body contains a string
    literal starting with ``"aria2."`` or ``"system."`` (the RPC method
    name passed to ``aria_rpc``). Everything else is a helper.
    """
    text = _read(_PROJECT / "src" / "aria_queue" / "aria2_rpc.py")
    tree = ast.parse(text)
    wrappers: list[str] = []
    helpers: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("aria2_"):
            continue
        body_src = ast.get_source_segment(text, node) or ""
        if re.search(r'"(aria2|system)\.\w+"', body_src):
            wrappers.append(node.name)
        else:
            helpers.append(node.name)
    return sorted(wrappers), sorted(helpers)


def section_aria2() -> str:
    wrappers, helpers = _ast_aria2_functions()
    out = ["## 7. aria2 RPC integration", ""]
    out.append(
        f"`src/aria_queue/aria2_rpc.py` exposes **{len(wrappers)} 1:1 RPC wrappers** "
        f"(each wraps one `aria2.*` or `system.*` JSON-RPC method) plus "
        f"**{len(helpers)} orchestration helpers**."
    )
    out.append("")
    out.append("### 1:1 RPC wrappers")
    out.append("")
    for w in wrappers:
        out.append(f"- `{w}`")
    out.append("")
    out.append("### Orchestration helpers")
    out.append("")
    for h in helpers:
        out.append(f"- `{h}`")
    out.append("")
    return "\n".join(out)


def section_uic() -> str:
    from aria_queue.contracts import DEFAULT_DECLARATION

    gates = DEFAULT_DECLARATION.get("uic", {}).get("gates", [])
    prefs = DEFAULT_DECLARATION.get("uic", {}).get("preferences", [])
    out = ["## 8. UIC declaration", ""]
    out.append(f"**{len(gates)} preflight gates** + **{len(prefs)} preferences**.")
    out.append("")
    out.append("### Preflight gates")
    out.append("")
    out.append("| Name | Class | Blocking |")
    out.append("|---|---|---|")
    for g in gates:
        out.append(
            f"| `{g.get('name', '')}` | {g.get('class', '')} | {g.get('blocking', '')} |"
        )
    out.append("")
    out.append("### Preferences")
    out.append("")
    out.append("| Name | Default | Options | Rationale |")
    out.append("|---|---|---|---|")
    for p in prefs:
        opts = p.get("options", [])
        opts_str = ", ".join(f"`{o}`" for o in opts) if opts else "_open_"
        rationale = (p.get("rationale") or "").replace("|", "\\|")
        out.append(
            f"| `{p.get('name', '')}` | `{p.get('value', '')}` | {opts_str} | {rationale} |"
        )
    out.append("")
    return "\n".join(out)


def section_queue_item() -> str:
    from dataclasses import fields
    from aria_queue.queue_ops import QueueItem

    out = ["## 9. Queue item shape", ""]
    out.append(
        "`QueueItem` dataclass — single source of truth for the shape of "
        "every entry in `queue.json` and `archive.json`."
    )
    out.append("")
    out.append("| Field | Type | Default |")
    out.append("|---|---|---|")
    for f in fields(QueueItem):
        type_str = str(f.type).replace("typing.", "")
        if f.default is not None and f.default.__class__.__name__ != "_MISSING_TYPE":
            default_str = f"`{f.default!r}`"
        elif (
            getattr(f, "default_factory", None) is not None
            and f.default_factory.__class__.__name__ != "_MISSING_TYPE"
        ):
            default_str = "_factory_"
        else:
            default_str = "_required_"
        out.append(f"| `{f.name}` | `{type_str}` | {default_str} |")
    out.append("")
    return "\n".join(out)


def section_bgs() -> str:
    decision_path = _PROJECT / "docs" / "governance" / "bgs-decision.yaml"
    text = _read(decision_path)

    # Tiny YAML extraction — only the scalar fields we want.
    def _scalar(key: str) -> str:
        m = re.search(rf"^{key}\s*:\s*(.+?)$", text, re.MULTILINE)
        return m.group(1).strip().strip('"').strip("'") if m else ""

    def _list(key: str) -> list[str]:
        m = re.search(rf"^{key}\s*:\n((?:  - .+\n?)+)", text, re.MULTILINE)
        if not m:
            return []
        return [line.strip("- ").strip() for line in m.group(1).splitlines()]

    out = ["## 10. BGS claim", ""]
    out.append(f"- **Decision ID:** `{_scalar('decision_id')}`")
    out.append(f"- **Slice:** `{_scalar('bgs_slice')}`")
    out.append(f"- **Scope:** {_scalar('declared_scope')}")
    out.append(f"- **BGS version:** `{_scalar('bgs_version_ref')}`")
    out.append(f"- **Owner:** {_scalar('owner')}")
    out.append(f"- **Date:** {_scalar('date')}")
    members = _list("members_used")
    if members:
        out.append(f"- **Members used:** {', '.join(f'`{m}`' for m in members)}")
    overlays = _list("overlays_used")
    out.append(
        f"- **Overlays used:** {', '.join(f'`{o}`' for o in overlays) if overlays else '_none_'}"
    )
    out.append("")
    out.append("### Member version refs")
    out.append("")
    refs_block = re.search(
        r"^member_version_refs\s*:\n((?:  [a-z]+:.*\n?)+)", text, re.MULTILINE
    )
    if refs_block:
        for line in refs_block.group(1).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(f"- `{line}`")
    out.append("")
    out.append("### External controls")
    out.append("")
    ec_block = re.search(
        r"^external_controls\s*:\n((?:  [a-z_]+:.*\n?)+)", text, re.MULTILINE
    )
    if ec_block:
        for line in ec_block.group(1).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                key, _, val = stripped.partition(":")
                out.append(f"- **{key.strip()}:** `{val.strip()}`")
    out.append("")
    out.append("### Evidence refs")
    out.append("")
    ev_block = re.search(r"^evidence_refs\s*:\n((?:  - .+\n?)+)", text, re.MULTILINE)
    if ev_block:
        for line in ev_block.group(1).splitlines():
            ref = line.strip().lstrip("-").strip()
            # Strip trailing inline comment.
            ref = re.split(r"\s+#", ref)[0].strip()
            if ref:
                out.append(f"- `{ref}`")
    out.append("")
    return "\n".join(out)


def section_tests() -> str:
    """Run pytest --collect-only and tally tests per file."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
        capture_output=True,
        text=True,
        cwd=_PROJECT,
    )
    by_file: dict[str, int] = {}
    total = 0
    for line in result.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        file_part = line.split("::", 1)[0]
        by_file[file_part] = by_file.get(file_part, 0) + 1
        total += 1

    out = ["## 11. Test coverage", ""]
    out.append(
        f"**{total} tests collected** across {len(by_file)} files (collection-mode form). "
        f"Runtime count includes parametrized cases — see `make test`."
    )
    out.append("")
    out.append("| Test file | Count |")
    out.append("|---|---|")
    for path in sorted(by_file):
        out.append(f"| `{path}` | {by_file[path]} |")
    out.append("")
    out.append(
        "Every test is registered in `docs/governance/tic-oracle.md` "
        "with an Intent / Oracle / Trace Target row. "
        "`scripts/check_tic_coverage.py` (wired into `make verify`) "
        "fails on any unregistered test."
    )
    out.append("")
    return "\n".join(out)


def section_regenerate() -> str:
    return (
        "## 12. How to regenerate\n"
        "\n"
        "```\n"
        "python scripts/gen_spec.py\n"
        "```\n"
        "\n"
        "`scripts/check_spec.py` (run by `make check-drift`) regenerates "
        "this file to a temporary path and fails if it differs from the "
        "committed `docs/SPEC.md`. Re-run after any change to:\n"
        "\n"
        "- `docs/GOAL.md`\n"
        "- `pyproject.toml`\n"
        "- `src/aria_queue/webapp.py` (dispatch tables)\n"
        "- `src/aria_queue/openapi_schemas.py`\n"
        "- `src/aria_queue/contracts.py`\n"
        "- `src/aria_queue/queue_ops.py`\n"
        "- `src/aria_queue/aria2_rpc.py`\n"
        "- any file under `docs/governance/`\n"
    )


# ── main ─────────────────────────────────────────────────────────────


def render() -> str:
    sha = _git_sha()
    commit_date = _git_commit_date()
    header = (
        "# Ariaflow — Specification\n"
        "\n"
        f"> Generated by `scripts/gen_spec.py` from commit `{sha}` ({commit_date}).\n"
        ">\n"
        "> Do not edit by hand. Edit `docs/GOAL.md` for the goal section, "
        "edit code or governance artifacts for everything else, then re-run "
        "`python scripts/gen_spec.py`.\n"
        "\n"
    )
    sections = [
        section_goal(),
        section_identity(),
        section_architecture(),
        section_asm(),
        section_biss(),
        section_http_api(),
        section_aria2(),
        section_uic(),
        section_queue_item(),
        section_bgs(),
        section_tests(),
        section_regenerate(),
    ]
    return header + "\n".join(sections)


def main() -> int:
    text = render()
    _OUTPUT.write_text(text, encoding="utf-8")
    print(f"Generated {_OUTPUT.relative_to(_PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
