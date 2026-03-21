from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .core import config_dir, queue_path


DEFAULT_DECLARATION = {
    "meta": {"contract": "UCC", "version": "2.0"},
    "uic": {
        "gates": [
            {"name": "aria2_available", "class": "readiness", "blocking": "hard"},
            {"name": "queue_readable", "class": "integrity", "blocking": "hard"},
        ],
        "preferences": [
            {"name": "post_action_rule", "value": "pending", "options": ["pending"], "rationale": "default placeholder"}
        ],
        "policies": [],
    },
    "targets": [
        {"name": "queue", "type": "queue"},
    ],
}


def declaration_path() -> Path:
    return config_dir() / "declaration.json"


def ensure_declaration() -> dict[str, Any]:
    path = declaration_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_DECLARATION, indent=2) + "\n", encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def load_declaration() -> dict[str, Any]:
    return ensure_declaration()


def preflight() -> dict[str, Any]:
    decl = load_declaration()
    gates = []
    failures = []

    aria_ok = True
    try:
        from .core import aria_rpc
        aria_rpc("aria2.getVersion")
    except Exception:
        aria_ok = False

    queue_ok = queue_path().parent.exists()

    for gate in decl.get("uic", {}).get("gates", []):
        name = gate["name"]
        satisfied = True
        if name == "aria2_available":
            satisfied = aria_ok
        elif name == "queue_readable":
            satisfied = queue_ok
        gates.append({"name": name, "satisfied": satisfied, "blocking": gate.get("blocking", "hard"), "class": gate.get("class", "readiness")})
        if not satisfied and gate.get("blocking", "hard") == "hard":
            failures.append(name)

    return {
        "contract": decl.get("meta", {}).get("contract", "UCC"),
        "version": decl.get("meta", {}).get("version", "2.0"),
        "gates": gates,
        "preferences": decl.get("uic", {}).get("preferences", []),
        "policies": decl.get("uic", {}).get("policies", []),
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "exit_code": 0 if not failures else 1,
    }


@dataclass
class UCCResult:
    observation: str
    outcome: str
    completion: str | None = None
    failure_class: str | None = None
    inhibitor: str | None = None
    partial: bool | None = None
    message: str = ""
    reason: str = "aggregate"
    observed_before: dict[str, Any] | None = None
    observed_after: dict[str, Any] | None = None
    diff: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {k: v for k, v in payload.items() if v is not None and v != ""}


def run_ucc(port: int = 6800) -> dict[str, Any]:
    from .core import load_queue, process_queue

    pf = preflight()
    if pf["exit_code"] != 0:
        return {
            "meta": {"contract": "UCC", "version": "2.0"},
            "result": UCCResult(
                observation="failed",
                outcome="failed",
                completion=None,
                failure_class="permanent",
                message="preflight failed",
                reason="gate_failed",
                observed_before={"gates": pf["gates"]},
                diff={"failures": pf["failures"]},
            ).to_dict(),
            "preflight": pf,
        }

    before = load_queue()
    after = process_queue(port=port)
    changed = before != after
    failed = any(item.get("status") == "error" for item in after)
    return {
        "meta": {"contract": "UCC", "version": "2.0"},
        "result": UCCResult(
            observation="ok",
            outcome="changed" if changed else "converged",
            completion="complete" if changed else None,
            partial=failed if changed else None,
            message="queue processed",
            reason="changed" if changed else "converged",
            observed_before={"items": before},
            observed_after={"items": after},
            diff={"count": len(after) - len(before)},
        ).to_dict(),
        "preflight": pf,
    }
