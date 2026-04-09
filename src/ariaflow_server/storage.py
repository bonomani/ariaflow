from __future__ import annotations

from contextlib import contextmanager
import json
import os
import shutil
import time
import threading
import portalocker
from pathlib import Path
from typing import Any


_STORAGE_LOCK = threading.RLock()
_STORAGE_LOCK_STATE = threading.local()


def config_dir() -> Path:
    explicit = os.environ.get("ARIAFLOW_DIR") or os.environ.get("ARIA_QUEUE_DIR")
    if explicit:
        return Path(explicit)
    new = Path.home() / ".config" / "ariaflow-server"
    old = Path.home() / ".config" / "aria-queue"
    if not new.exists() and old.exists():
        try:
            old.rename(new)
        except OSError as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to migrate config dir %s → %s: %s", old, new, exc
            )
            return old
    return new


def queue_path() -> Path:
    return config_dir() / "queue.json"


def state_path() -> Path:
    return config_dir() / "state.json"


def log_path() -> Path:
    return config_dir() / "aria2.log"


def action_log_path() -> Path:
    return config_dir() / "actions.jsonl"


def archive_path() -> Path:
    return config_dir() / "archive.json"


def sessions_log_path() -> Path:
    return config_dir() / "sessions.jsonl"


def storage_lock_path() -> Path:
    return config_dir() / ".storage.lock"


def ensure_storage() -> None:
    config_dir().mkdir(parents=True, exist_ok=True)


@contextmanager
def storage_locked() -> Any:
    ensure_storage()
    with _STORAGE_LOCK:
        depth = getattr(_STORAGE_LOCK_STATE, "depth", 0)
        handle = getattr(_STORAGE_LOCK_STATE, "handle", None)
        if depth == 0 or handle is None:
            handle = storage_lock_path().open("a+", encoding="utf-8")
            try:
                portalocker.lock(handle, portalocker.LOCK_EX)
            except Exception:
                handle.close()
                raise
            _STORAGE_LOCK_STATE.handle = handle
        _STORAGE_LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            next_depth = getattr(_STORAGE_LOCK_STATE, "depth", 1) - 1
            _STORAGE_LOCK_STATE.depth = next_depth
            if next_depth == 0:
                current = getattr(_STORAGE_LOCK_STATE, "handle", None)
                if current is not None:
                    portalocker.unlock(current)
                    current.close()
                if hasattr(_STORAGE_LOCK_STATE, "handle"):
                    delattr(_STORAGE_LOCK_STATE, "handle")
                if hasattr(_STORAGE_LOCK_STATE, "depth"):
                    delattr(_STORAGE_LOCK_STATE, "depth")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        time.sleep(0.05)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            bak = path.with_suffix(path.suffix + ".corrupt.bak")
            try:
                shutil.copy2(path, bak)
            except Exception:
                pass
            return default


def write_json(path: Path, value: Any) -> None:
    ensure_storage()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
