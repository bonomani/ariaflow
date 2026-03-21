from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import threading
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from uuid import uuid4


def config_dir() -> Path:
    return Path(os.environ.get("ARIA_QUEUE_DIR", Path.home() / ".config" / "aria-queue"))


def queue_path() -> Path:
    return config_dir() / "queue.json"


def state_path() -> Path:
    return config_dir() / "state.json"


def log_path() -> Path:
    return config_dir() / "aria2.log"


def action_log_path() -> Path:
    return config_dir() / "actions.jsonl"


def ensure_storage() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    ensure_storage()
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_action_log(entry: dict[str, Any]) -> None:
    ensure_storage()
    payload = dict(entry)
    payload.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    with action_log_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def load_action_log(limit: int = 200) -> list[dict[str, Any]]:
    path = action_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"error": "invalid_log_entry", "raw": line})
    return entries


def record_action(
    *,
    action: str,
    target: str,
    outcome: str,
    observation: str = "ok",
    reason: str = "aggregate",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "action": action,
        "target": target,
        "outcome": outcome,
        "observation": observation,
        "reason": reason,
    }
    if before is not None:
        entry["observed_before"] = before
    if after is not None:
        entry["observed_after"] = after
    if detail is not None:
        entry["detail"] = detail
    append_action_log(entry)
    return entry


def log_transfer_poll(
    *,
    gid: str,
    item: dict[str, Any],
    info: dict[str, Any],
    cap_mbps: int | None = None,
) -> None:
    record_action(
        action="poll",
        target="queue_item",
        outcome=info.get("status", "unknown"),
        reason="aria2_poll",
        before={"item": dict(item)},
        after={
            "status": info.get("status"),
            "downloadSpeed": info.get("downloadSpeed"),
            "completedLength": info.get("completedLength"),
            "totalLength": info.get("totalLength"),
            "errorCode": info.get("errorCode"),
            "errorMessage": info.get("errorMessage"),
            "cap_mbps": cap_mbps,
        },
        detail={
            "item_id": item.get("id"),
            "gid": gid,
            "url": item.get("url"),
            "downloadSpeed": info.get("downloadSpeed"),
            "completedLength": info.get("completedLength"),
            "totalLength": info.get("totalLength"),
            "status": info.get("status"),
        },
    )


def load_state() -> dict[str, Any]:
    return read_json(state_path(), {"paused": False, "active_gid": None, "active_url": None})


def save_state(state: dict[str, Any]) -> None:
    write_json(state_path(), state)


def start_background_process(port: int = 6800) -> dict[str, Any]:
    state = load_state()
    if state.get("running"):
        return {"started": False, "reason": "already_running"}

    state["running"] = True
    save_state(state)

    def _runner() -> None:
        try:
            process_queue(port=port)
        except Exception as exc:
            current = load_state()
            current["last_error"] = str(exc)
            current["running"] = False
            current["active_gid"] = None
            current["active_url"] = None
            save_state(current)
        finally:
            current = load_state()
            current["running"] = False
            current["active_gid"] = None
            current["active_url"] = None
            save_state(current)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return {"started": True, "reason": "background"}


@dataclass
class QueueItem:
    id: str
    url: str
    output: str | None = None
    post_action_rule: str = "pending"
    status: str = "queued"
    created_at: str = ""
    gid: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def load_queue() -> list[dict[str, Any]]:
    data = read_json(queue_path(), {"items": []})
    return list(data.get("items", []))


def summarize_queue(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(items),
        "queued": sum(1 for item in items if item.get("status") == "queued"),
        "downloading": sum(1 for item in items if item.get("status") == "downloading"),
        "paused": sum(1 for item in items if item.get("status") == "paused"),
        "done": sum(1 for item in items if item.get("status") == "done"),
        "error": sum(1 for item in items if item.get("status") == "error"),
    }


def save_queue(items: list[dict[str, Any]]) -> None:
    write_json(queue_path(), {"items": items})


def add_queue_item(url: str, output: str | None = None, post_action_rule: str = "pending") -> QueueItem:
    from .contracts import load_declaration

    ensure_storage()
    before = {"summary": summarize_queue(load_queue())}
    decl = load_declaration()
    default_rule = decl.get("uic", {}).get("preferences", [{}])[0].get("value", "pending")
    item = QueueItem(
        id=str(uuid4()),
        url=url,
        output=output,
        post_action_rule=post_action_rule or default_rule,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    items = load_queue()
    items.append(asdict(item))
    save_queue(items)
    record_action(
        action="add",
        target="queue",
        outcome="changed",
        reason="queue_item_created",
        before=before,
        after={"summary": summarize_queue(items), "item_id": item.id},
        detail={
            "item_id": item.id,
            "url": url,
            "output": output,
            "post_action_rule": item.post_action_rule,
        },
    )
    return item


def probe_bandwidth(percent: float = 0.8, floor_mbps: int = 2) -> dict[str, Any]:
    cmd = shutil.which("networkquality")
    if cmd is None:
        for candidate in ("/usr/bin/networkquality", "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkquality"):
            if Path(candidate).exists():
                cmd = candidate
                break
    if cmd:
        try:
            completed = subprocess.run([cmd], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12)
            out = completed.stdout
            match = re.search(r"Downlink:\s+([\d.]+)\s+Mbps", out)
            if match:
                downlink = float(match.group(1))
                cap = max(floor_mbps, int(downlink * percent))
                return {"source": "networkquality", "downlink_mbps": downlink, "cap_mbps": cap}
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            match = re.search(r"Downlink:\s+([\d.]+)\s+Mbps", out)
            if match:
                downlink = float(match.group(1))
                cap = max(floor_mbps, int(downlink * percent))
                return {"source": "networkquality", "downlink_mbps": downlink, "cap_mbps": cap, "partial": True}
        except Exception:
            pass
    return {"source": "default", "downlink_mbps": None, "cap_mbps": floor_mbps}


def aria_rpc(method: str, params: list[Any] | None = None, port: int = 6800) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": "aria-queue",
        "method": method,
        "params": params or [],
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/jsonrpc",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_aria_daemon(port: int = 6800) -> None:
    try:
        aria_rpc("aria2.getVersion", port=port)
        return
    except Exception:
        pass

    args = [
        "aria2c",
        "--enable-rpc=true",
        "--rpc-listen-all=false",
        f"--rpc-listen-port={port}",
        "--rpc-allow-origin-all=true",
        "--console-log-level=warn",
        "--summary-interval=0",
        f"--log={log_path()}",
        "--log-level=warn",
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


def add_download(item: dict[str, Any], cap_mbps: int, port: int = 6800) -> str:
    options = {
        "max-download-limit": f"{cap_mbps}M",
        "allow-overwrite": "true",
        "continue": "true",
    }
    uris = [item["url"]]
    result = aria_rpc("aria2.addUri", [uris, options], port=port)
    return result["result"]


def status(gid: str, port: int = 6800) -> dict[str, Any]:
    fields = ["status", "errorCode", "errorMessage", "downloadSpeed", "completedLength", "totalLength", "files"]
    result = aria_rpc("aria2.tellStatus", [gid, fields], port=port)
    return result["result"]


def aria_status(port: int = 6800) -> dict[str, Any]:
    try:
        version = aria_rpc("aria2.getVersion", port=port)["result"]["version"]
    except Exception as exc:
        return {"reachable": False, "version": None, "error": str(exc)}
    return {"reachable": True, "version": version, "error": None}


def active_status(port: int = 6800) -> dict[str, Any] | None:
    state = load_state()
    gid = state.get("active_gid")
    if not gid:
        return None
    try:
        info = status(gid, port=port)
    except Exception as exc:
        return {
            "gid": gid,
            "url": state.get("active_url"),
            "status": "unknown",
            "errorMessage": str(exc),
            "downloadSpeed": None,
            "completedLength": None,
            "totalLength": None,
            "percent": 0,
        }
    total = float(info.get("totalLength") or 0)
    done = float(info.get("completedLength") or 0)
    percent = round((done / total) * 100, 1) if total else 0
    return {
        "gid": gid,
        "url": state.get("active_url"),
        "status": info.get("status"),
        "errorCode": info.get("errorCode"),
        "errorMessage": info.get("errorMessage"),
        "downloadSpeed": info.get("downloadSpeed"),
        "completedLength": info.get("completedLength"),
        "totalLength": info.get("totalLength"),
        "files": info.get("files"),
        "percent": percent,
    }


def set_bandwidth(cap_mbps: int, port: int = 6800) -> None:
    aria_rpc("aria2.changeGlobalOption", [{"max-overall-download-limit": f"{cap_mbps}M"}], port=port)


def current_bandwidth(port: int = 6800) -> dict[str, Any]:
    try:
        result = aria_rpc("aria2.getGlobalOption", port=port)["result"]
        return {
            "limit": result.get("max-overall-download-limit"),
            "dir": result.get("dir"),
            "seed-ratio": result.get("seed-ratio"),
        }
    except Exception as exc:
        return {"limit": None, "error": str(exc)}


def pause_active_transfer(port: int = 6800) -> dict[str, Any]:
    state = load_state()
    gid = state.get("active_gid")
    if not gid:
        return {"paused": False, "reason": "no_active_transfer"}
    before = {"state": state, "active": active_status(port=port)}
    result = aria_rpc("aria2.pause", [gid], port=port)
    state["paused"] = True
    save_state(state)
    payload = {"paused": True, "gid": gid, "result": result.get("result")}
    record_action(
        action="pause",
        target="active_transfer",
        outcome="changed",
        reason="user_pause",
        before=before,
        after={"state": load_state(), "active": active_status(port=port)},
        detail={"gid": gid, "result": payload},
    )
    return payload


def resume_active_transfer(port: int = 6800) -> dict[str, Any]:
    state = load_state()
    gid = state.get("active_gid")
    if not gid:
        return {"resumed": False, "reason": "no_active_transfer"}
    before = {"state": state, "active": active_status(port=port)}
    result = aria_rpc("aria2.unpause", [gid], port=port)
    state["paused"] = False
    save_state(state)
    payload = {"resumed": True, "gid": gid, "result": result.get("result")}
    record_action(
        action="resume",
        target="active_transfer",
        outcome="changed",
        reason="user_resume",
        before=before,
        after={"state": load_state(), "active": active_status(port=port)},
        detail={"gid": gid, "result": payload},
    )
    return payload


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_rate(bytes_per_second: int | float | None) -> str:
    if bytes_per_second is None:
        return "-"
    return f"{format_bytes(bytes_per_second)}/s"


def format_mbps(value: int | float | None) -> str:
    if value is None:
        return "-"
    return f"{value} Mbps"


def post_action(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "reason": item.get("post_action_rule", "pending"),
        "detail": "post action policy not defined yet",
        "item_id": item["id"],
    }


def process_queue(port: int = 6800) -> list[dict[str, Any]]:
    ensure_storage()
    ensure_aria_daemon(port=port)
    probe = probe_bandwidth()
    cap = int(probe["cap_mbps"])
    record_action(
        action="probe",
        target="bandwidth",
        outcome="changed" if probe.get("source") == "networkquality" else "unchanged",
        reason=probe.get("source", "default"),
        before={"cap": current_bandwidth(port=port)},
        after={"probe": probe, "cap_mbps": cap},
        detail=probe,
    )
    items = load_queue()
    state = load_state()

    for item in items:
        if load_state().get("paused"):
            break
        if item.get("status") == "done":
            continue
        item["status"] = "downloading"
        gid = add_download(item, cap_mbps=cap, port=port)
        item["gid"] = gid
        record_action(
            action="run",
            target="queue_item",
            outcome="changed",
            reason="download_started",
            before={"item": dict(item)},
            after={"item": dict(item), "gid": gid, "cap_mbps": cap},
            detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "cap_mbps": cap},
        )
        state["active_gid"] = gid
        state["active_url"] = item.get("url")
        save_state(state)
        while True:
            time.sleep(2)
            if load_state().get("paused"):
                item["status"] = "paused"
                save_queue(items)
                state["paused"] = True
                state["active_gid"] = gid
                state["active_url"] = item.get("url")
                save_state(state)
                break
            info = status(gid, port=port)
            log_transfer_poll(gid=gid, item=item, info=info, cap_mbps=cap)
            if info.get("errorCode") and info["errorCode"] != "0":
                cap = max(1, int(cap * 0.75))
                set_bandwidth(cap, port=port)
            if info.get("status") == "complete":
                item["status"] = "done"
                item["post_action"] = post_action(item)
                record_action(
                    action="complete",
                    target="queue_item",
                    outcome="converged",
                    reason="download_complete",
                    before={"item": dict(item), "status": "downloading"},
                    after={"item": dict(item), "post_action": item.get("post_action")},
                    detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "result": item.get("post_action")},
                )
                break
            if info.get("status") == "error":
                item["status"] = "error"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                record_action(
                    action="error",
                    target="queue_item",
                    outcome="failed",
                    reason="download_error",
                    before={"item": dict(item), "status": "downloading"},
                    after={"item": dict(item), "error_code": item.get("error_code"), "error_message": item.get("error_message")},
                    detail={"item_id": item.get("id"), "gid": gid, "url": item.get("url"), "error_code": item.get("error_code"), "error_message": item.get("error_message")},
                )
                break
        if item.get("status") in {"done", "error"}:
            state["active_gid"] = None
            state["active_url"] = None
        save_state(state)
    save_queue(items)
    return items


def get_active_progress(port: int = 6800) -> dict[str, Any] | None:
    state = load_state()
    gid = state.get("active_gid")
    if not gid:
        return None
    try:
        info = status(gid, port=port)
    except Exception as exc:
        return {"gid": gid, "error": str(exc), "url": state.get("active_url")}

    total = int(info.get("totalLength") or 0)
    completed = int(info.get("completedLength") or 0)
    speed = int(info.get("downloadSpeed") or 0)
    percent = round((completed / total) * 100, 2) if total else None
    return {
        "gid": gid,
        "url": state.get("active_url"),
        "status": info.get("status"),
        "download_speed": speed,
        "completed_length": completed,
        "total_length": total,
        "percent": percent,
        "error_code": info.get("errorCode"),
        "error_message": info.get("errorMessage"),
    }
