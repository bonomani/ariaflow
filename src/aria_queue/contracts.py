from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .core import (
    aria_rpc,
    config_dir,
    aria2_ensure_daemon,
    get_active_progress,
    load_state,
    queue_path,
    storage_locked,
    summarize_queue,
)


DEFAULT_DECLARATION = {
    "meta": {"contract": "UCC", "version": "2.0"},
    "uic": {
        "gates": [
            {"name": "aria2_available", "class": "readiness", "blocking": "hard"},
            {"name": "queue_readable", "class": "integrity", "blocking": "hard"},
        ],
        "preferences": [
            {
                "name": "post_action_rule",
                "value": "pending",
                "options": ["pending"],
                "rationale": "default placeholder",
            },
            {
                "name": "auto_preflight_on_run",
                "value": False,
                "options": [True, False],
                "rationale": "default off",
            },
            {
                "name": "duplicate_active_transfer_action",
                "value": "remove",
                "options": ["remove", "pause", "ignore"],
                "rationale": "remove duplicate live jobs by default",
            },
            {
                "name": "max_simultaneous_downloads",
                "value": 1,
                "options": [1],
                "rationale": "1 preserves the sequential default",
            },
            {
                "name": "bandwidth_down_free_percent",
                "value": 20,
                "options": [0, 10, 20, 30, 50],
                "rationale": "reserve this % of downlink for other traffic",
            },
            {
                "name": "bandwidth_down_free_absolute_mbps",
                "value": 0,
                "options": [0, 1, 2, 5, 10],
                "rationale": "reserve this many Mbps downlink (0 = use percent only; stricter of % and absolute wins)",
            },
            {
                "name": "bandwidth_up_free_percent",
                "value": 50,
                "options": [0, 10, 20, 30, 50, 80],
                "rationale": "reserve this % of uplink for other traffic",
            },
            {
                "name": "bandwidth_up_free_absolute_mbps",
                "value": 0,
                "options": [0, 1, 2, 5, 10],
                "rationale": "reserve this many Mbps uplink (0 = use percent only; stricter of % and absolute wins)",
            },
            {
                "name": "bandwidth_probe_interval_seconds",
                "value": 180,
                "options": [60, 120, 180, 300],
                "rationale": "seconds between automatic bandwidth probes",
            },
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
    with storage_locked():
        path = declaration_path()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(DEFAULT_DECLARATION, indent=2) + "\n", encoding="utf-8"
            )
        return json.loads(path.read_text(encoding="utf-8"))


def load_declaration() -> dict[str, Any]:
    return ensure_declaration()


def save_declaration(declaration: dict[str, Any]) -> dict[str, Any]:
    with storage_locked():
        path = declaration_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(declaration, indent=2) + "\n", encoding="utf-8")
        return declaration


def _aria2_available(port: int = 6800) -> bool:
    try:
        aria_rpc("aria2.getVersion", port=port)
        return True
    except Exception:
        pass

    try:
        aria2_ensure_daemon(port=port)
        aria_rpc("aria2.getVersion", port=port)
        return True
    except Exception:
        return False


def preflight() -> dict[str, Any]:
    decl = load_declaration()
    gates = []
    failures = []

    aria_ok = _aria2_available()

    queue_ok = queue_path().parent.exists()
    state = load_state()
    warnings = []

    for gate in decl.get("uic", {}).get("gates", []):
        name = gate["name"]
        satisfied = True
        if name == "aria2_available":
            satisfied = aria_ok
        elif name == "queue_readable":
            satisfied = queue_ok
        elif name == "paused":
            satisfied = not state.get("paused", False)
            if not satisfied:
                warnings.append({"name": name, "message": "queue is paused"})
        gates.append(
            {
                "name": name,
                "satisfied": satisfied,
                "blocking": gate.get("blocking", "hard"),
                "class": gate.get("class", "readiness"),
            }
        )
        if not satisfied and gate.get("blocking", "hard") == "hard":
            failures.append(name)

    return {
        "contract": decl.get("meta", {}).get("contract", "UCC"),
        "version": decl.get("meta", {}).get("version", "2.0"),
        "gates": gates,
        "preferences": decl.get("uic", {}).get("preferences", []),
        "policies": decl.get("uic", {}).get("policies", []),
        "warnings": warnings,
        "hard_failures": failures,
        "status": "pass" if not failures else "fail",
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
                diff={"failures": pf["hard_failures"]},
            ).to_dict(),
            "preflight": pf,
        }

    before = load_queue()
    after = process_queue(port=port)
    changed = before != after
    failed = any(item.get("status") == "error" for item in after)
    active = get_active_progress(port=port)
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
            diff={
                "count_delta": len(after) - len(before),
                "summary": summarize_queue(after),
                "active": active,
            },
        ).to_dict(),
        "preflight": pf,
    }
