#!/usr/bin/env python3
"""Check BGS governance coverage of project code.

Detects Type 2 drift — where the project grew beyond what the BGS slice models.

For each source module in ``src/ariaflow_server/``, this script verifies it is
referenced in at least one governance artifact:
- ``docs/governance/biss-classification.md`` (BISS boundary notes)
- ``docs/governance/asm-state-model.md`` (ASM axis definitions)
- ``docs/governance/tic-oracle.md`` (TIC trace targets)
- ``docs/governance/bgs-decision.yaml`` (evidence_refs paths)

Modules absent from all four are "ungoverned scope" — they need either:
- A new governance entry (add the concept to BGS)
- An explicit exclusion note (acknowledge it's outside BGS scope)

Exit 1 if any production module lacks coverage.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT / "src" / "ariaflow_server"
_GOV = _PROJECT / "docs" / "governance"

# Modules excluded from coverage checks (infrastructure, not governed scope)
_EXCLUSIONS = {
    "__init__",
    "__main__",
    "cli",             # CLI entrypoint, no state
    "core",            # re-export hub, no logic
    "api",             # re-export hub, no logic
    "install",         # one-shot installer, not runtime
    "openapi_schemas", # generator data
}

# Module → governance concepts (at least one must appear in the corpus).
# A module is covered if ANY of its listed concepts is mentioned in the
# governance docs. This decouples filenames from governance vocabulary.
_MODULE_CONCEPTS: dict[str, list[str]] = {
    "aria2_rpc":  ["aria2 RPC", "aria2_"],
    "bandwidth":  ["bandwidth", "networkQuality"],
    "bonjour":    ["Bonjour", "mDNS"],
    "contracts":  ["UIC", "declaration", "preference"],
    "discovery":  ["Peer axis", "peer_discovered", "discovery.py", "auto_discover_peers"],
    "queue_ops":  ["Job axis", "QueueItem", "queue_item"],
    "reconcile":  ["reconcile", "dedup"],
    "scheduler":  ["Run axis", "scheduler", "process_queue"],
    "state":      ["Session axis", "ASM", "state.json"],
    "storage":    ["File lock", "storage_locked", "queue.json"],
    "torrent":    ["torrent", "distribute", "distribution"],
    "transfers":  ["active_transfer", "pause", "resume"],
    "webapp":     ["HTTP API", "af-api", "/api/"],
}


def _list_modules() -> list[str]:
    """Return stem names of all .py files in src/ariaflow_server/."""
    return sorted(p.stem for p in _SRC.glob("*.py"))


def _governance_corpus() -> str:
    """Concatenate all governance doc text for substring search."""
    parts = []
    for name in ("biss-classification.md", "asm-state-model.md",
                 "tic-oracle.md", "bgs-decision.yaml", "BGS.md"):
        path = _GOV / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _is_referenced(module: str, corpus: str) -> bool:
    """A module is covered if any of its concept keywords appears in the corpus.

    Falls back to filename match if no concepts are declared for the module.
    """
    concepts = _MODULE_CONCEPTS.get(module)
    if concepts is None:
        # Unknown module — require a filename reference (conservative)
        patterns = [f"{module}.py", f"ariaflow_server/{module}", f"ariaflow_server.{module}"]
        return any(p in corpus for p in patterns)
    return any(c in corpus for c in concepts)


def main() -> int:
    corpus = _governance_corpus()
    modules = _list_modules()

    ungoverned = []
    covered = []
    excluded = []

    for module in modules:
        if module in _EXCLUSIONS:
            excluded.append(module)
            continue
        if _is_referenced(module, corpus):
            covered.append(module)
        else:
            ungoverned.append(module)

    print(f"BGS coverage: {len(covered)}/{len(covered) + len(ungoverned)} production modules")
    print(f"  Covered:    {', '.join(covered)}")
    if excluded:
        print(f"  Excluded:   {', '.join(excluded)}")
    if ungoverned:
        print(f"\n  UNGOVERNED ({len(ungoverned)}):")
        for m in ungoverned:
            path = _SRC / f"{m}.py"
            lines = len(path.read_text(encoding="utf-8").splitlines())
            print(f"    - {m} ({lines} lines)")
        print("\n  Each ungoverned module should either:")
        print("    (a) be added to a governance artifact (BISS/ASM/TIC/BGS), or")
        print("    (b) be added to _EXCLUSIONS in this script with a reason.")
        return 1

    print("\nAll production modules covered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
