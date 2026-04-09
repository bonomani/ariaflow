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
            {
                "name": "aria2_unsafe_options",
                "value": False,
                "options": [False, True],
                "rationale": "allow setting any aria2 option via API (bypasses safe subset)",
            },
            {
                "name": "max_retries",
                "value": 3,
                "options": [0, 1, 3, 5, 10],
                "rationale": "auto-retry failed downloads up to N times (0 = manual retry only)",
            },
            {
                "name": "archive_completed_after_hours",
                "value": 168,
                "options": [0, 1, 6, 12, 24, 72, 168],
                "rationale": "move completed downloads from queue to archive after N hours (0 = keep completed items in queue)",
            },
            {
                "name": "retry_backoff_seconds",
                "value": 30,
                "options": [10, 30, 60, 120, 300],
                "rationale": "seconds between auto-retries, multiplied by retry count",
            },
            {
                "name": "aria2_max_tries",
                "value": 5,
                "options": [1, 3, 5, 10, 0],
                "rationale": "aria2 retries per download for transient network errors (0 = unlimited)",
            },
            {
                "name": "aria2_retry_wait",
                "value": 10,
                "options": [3, 5, 10, 30, 60],
                "rationale": "seconds aria2 waits between retries",
            },
            {
                "name": "internal_tracker_url",
                "value": "",
                "options": [],
                "rationale": "internal BitTorrent tracker announce URL (empty = distribution disabled)",
            },
            {
                "name": "distribute_completed_downloads",
                "value": False,
                "options": [False, True],
                "rationale": "auto-create private torrent and seed after HTTP download completes",
            },
            {
                "name": "distribute_seed_ratio",
                "value": 0,
                "options": [0, 1, 2, 5],
                "rationale": "seed ratio for distributed torrents (0 = seed indefinitely)",
            },
            {
                "name": "distribute_max_seed_hours",
                "value": 72,
                "options": [24, 48, 72, 168, 0],
                "rationale": "stop seeding after N hours (0 = no time limit)",
            },
            {
                "name": "distribute_max_active_seeds",
                "value": 10,
                "options": [5, 10, 20, 50, 0],
                "rationale": "max concurrent seeds (0 = unlimited, oldest expired first)",
            },
            {
                "name": "max_disk_usage_percent",
                "value": 90,
                "options": [70, 80, 90, 95, 0],
                "rationale": "stop downloading when disk reaches this % usage (0 = no limit)",
            },
            {
                "name": "download_dir",
                "value": "",
                "options": [],
                "rationale": "download destination directory (empty = aria2 default / cwd)",
            },
            {
                "name": "torrent_dir",
                "value": "",
                "options": [],
                "rationale": "directory for .torrent files (empty = {config_dir}/torrents/)",
            },
            {
                "name": "auto_discover_peers",
                "value": False,
                "options": [False, True],
                "rationale": "browse local network for other ariaflow instances and auto-download their torrents",
            },
            {
                "name": "peer_poll_interval_seconds",
                "value": 60,
                "options": [30, 60, 120, 300],
                "rationale": "seconds between polling discovered peers for new torrents",
            },
            {
                "name": "peer_max_auto_downloads",
                "value": 5,
                "options": [1, 3, 5, 10, 0],
                "rationale": "max torrents to auto-fetch per poll cycle (0 = unlimited)",
            },
            {
                "name": "peer_content_filter",
                "value": "",
                "options": [],
                "rationale": "glob pattern to filter auto-downloaded torrents by name (empty = accept all)",
            },
            {
                "name": "peer_allowlist",
                "value": "",
                "options": [],
                "rationale": "comma-separated instance names to accept (empty = accept all peers)",
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


def pref_value(name: str, default: Any = None) -> Any:
    """Return the current value of a UIC preference by name."""
    for pref in load_declaration().get("uic", {}).get("preferences", []):
        if pref.get("name") == name:
            return pref.get("value", default)
    return default


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
