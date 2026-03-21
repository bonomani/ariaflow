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


def ensure_storage() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    ensure_storage()
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    return item


def probe_bandwidth(percent: float = 0.8, floor_mbps: int = 2) -> dict[str, Any]:
    cmd = shutil.which("networkquality")
    if cmd:
        try:
            out = subprocess.check_output([cmd], text=True, stderr=subprocess.DEVNULL)
            match = re.search(r"Downlink:\s+([\d.]+)\s+Mbps", out)
            if match:
                downlink = float(match.group(1))
                cap = max(floor_mbps, int(downlink * percent))
                return {"source": "networkquality", "downlink_mbps": downlink, "cap_mbps": cap}
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
        "max-overall-download-limit": f"{cap_mbps}M",
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


def set_bandwidth(cap_mbps: int, port: int = 6800) -> None:
    aria_rpc("aria2.changeGlobalOption", [{"max-overall-download-limit": f"{cap_mbps}M"}], port=port)


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
        state["active_gid"] = gid
        state["active_url"] = item.get("url")
        save_state(state)
        while True:
            time.sleep(2)
            if load_state().get("paused"):
                item["status"] = "paused"
                break
            info = status(gid, port=port)
            if info.get("errorCode") and info["errorCode"] != "0":
                cap = max(1, int(cap * 0.75))
                set_bandwidth(cap, port=port)
            if info.get("status") == "complete":
                item["status"] = "done"
                item["post_action"] = post_action(item)
                break
            if info.get("status") == "error":
                item["status"] = "error"
                item["error_code"] = info.get("errorCode")
                item["error_message"] = info.get("errorMessage")
                break
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
