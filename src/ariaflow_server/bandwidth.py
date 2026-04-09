from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .aria2_rpc import (
    _BITS_PER_MEGABIT,
    _BYTES_PER_MEGABIT,
    _cap_bytes_per_sec_from_mbps,
    _cap_mbps_from_bytes_per_sec,
)


def _core() -> Any:
    """Lazy import to allow patching through ariaflow_server.core."""
    from . import core

    return core


_NETWORKQUALITY_MAX_RUNTIME = 8
_NETWORKQUALITY_TIMEOUT = 10
_NETWORKQUALITY_PROBE_INTERVAL = 180
_NETWORKQUALITY_CANDIDATES = (
    "/usr/bin/networkQuality",
    "/usr/bin/networkquality",
    "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkQuality",
    "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/networkquality",
)


def _find_networkquality() -> str | None:
    for binary in ("networkQuality", "networkquality"):
        cmd = shutil.which(binary)
        if cmd is not None:
            return cmd
    for candidate in _NETWORKQUALITY_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _coerce_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def bandwidth_config() -> dict[str, Any]:
    from .contracts import pref_value

    down_free_pct = max(
        0, min(100, int(pref_value("bandwidth_down_free_percent", 20) or 20))
    )
    down_free_abs = max(
        0.0, float(pref_value("bandwidth_down_free_absolute_mbps", 0) or 0)
    )
    up_free_pct = max(
        0, min(100, int(pref_value("bandwidth_up_free_percent", 50) or 50))
    )
    up_free_abs = max(0.0, float(pref_value("bandwidth_up_free_absolute_mbps", 0) or 0))
    interval = max(30, int(pref_value("bandwidth_probe_interval_seconds", 180) or 180))
    return {
        "down_free_percent": down_free_pct,
        "down_free_absolute_mbps": down_free_abs,
        "down_use_percent": 1.0 - (down_free_pct / 100.0),
        "up_free_percent": up_free_pct,
        "up_free_absolute_mbps": up_free_abs,
        "up_use_percent": 1.0 - (up_free_pct / 100.0),
        "probe_interval_seconds": interval,
    }


def bandwidth_status(port: int = 6800) -> dict[str, Any]:
    core = _core()
    config = bandwidth_config()
    state = core.load_state()
    last_probe = state.get("last_bandwidth_probe")
    bw = core.aria2_current_bandwidth(port=port)
    result: dict[str, Any] = {
        "config": config,
        "current_limit": bw,
        "last_probe": last_probe if isinstance(last_probe, dict) else None,
        "last_probe_at": state.get("last_bandwidth_probe_at"),
    }
    if isinstance(last_probe, dict):
        result["interface"] = last_probe.get("interface_name")
        result["downlink_mbps"] = last_probe.get("downlink_mbps")
        result["uplink_mbps"] = last_probe.get("uplink_mbps")
        result["down_cap_mbps"] = last_probe.get("down_cap_mbps")
        result["up_cap_mbps"] = last_probe.get("up_cap_mbps")
        result["cap_bytes_per_sec"] = last_probe.get("cap_bytes_per_sec")
        result["responsiveness_rpm"] = last_probe.get("responsiveness_rpm")
    return result


def _apply_free_bandwidth_cap(
    measured_mbps: float | None,
    free_pct: int,
    free_abs: float,
) -> float | None:
    if not measured_mbps or measured_mbps <= 0:
        return None
    cap_from_pct = measured_mbps * (1.0 - free_pct / 100.0)
    cap = cap_from_pct
    if free_abs > 0:
        cap_from_abs = measured_mbps - free_abs
        cap = min(cap, cap_from_abs)
    return max(0.0, round(cap, 1))


def manual_probe(port: int = 6800) -> dict[str, Any]:
    core = _core()
    config = bandwidth_config()
    probe = core.probe_bandwidth(percent=config["down_use_percent"], floor_mbps=1)
    probe["interval_seconds"] = config["probe_interval_seconds"]

    down_mbps = probe.get("downlink_mbps")
    up_mbps = probe.get("uplink_mbps")
    down_cap = _apply_free_bandwidth_cap(
        down_mbps, config["down_free_percent"], config["down_free_absolute_mbps"]
    )
    up_cap = _apply_free_bandwidth_cap(
        up_mbps, config["up_free_percent"], config["up_free_absolute_mbps"]
    )
    probe["down_cap_mbps"] = down_cap
    probe["up_cap_mbps"] = up_cap
    if down_cap is not None:
        probe["cap_mbps"] = down_cap
        probe["cap_bytes_per_sec"] = max(1, int(down_cap * _BYTES_PER_MEGABIT))

    state = core.load_state()
    state["last_bandwidth_probe"] = probe
    state["last_bandwidth_probe_at"] = time.time()
    core.save_state(state)
    cap = probe.get("cap_bytes_per_sec", 0)
    up_cap_bytes = int(float(probe.get("up_cap_mbps") or 0) * 125_000.0)
    if cap > 0:
        try:
            core.aria2_set_max_overall_download_limit(cap, port=port)
        except Exception:
            pass
    if up_cap_bytes > 0:
        try:
            core.aria2_set_max_overall_upload_limit(up_cap_bytes, port=port)
        except Exception:
            pass
    core.record_action(
        action="probe",
        target="bandwidth",
        outcome="changed" if probe.get("source") == "networkquality" else "unchanged",
        reason="manual_probe",
        before={"config": config},
        after={"probe": probe},
        detail=probe,
    )
    return {
        "ok": True,
        "probe": probe,
        "config": config,
        "interface": probe.get("interface_name"),
        "downlink_mbps": down_mbps,
        "uplink_mbps": up_mbps,
        "down_cap_mbps": down_cap,
        "up_cap_mbps": up_cap,
        "cap_bytes_per_sec": probe.get("cap_bytes_per_sec"),
        "responsiveness_rpm": probe.get("responsiveness_rpm"),
        "source": probe.get("source"),
    }


def _default_bandwidth_probe(
    *,
    floor_mbps: int,
    reason: str,
    partial: bool = False,
    command: str | None = None,
) -> dict[str, Any]:
    cap_bytes_per_sec = int(floor_mbps * _BYTES_PER_MEGABIT)
    probe = {
        "source": "default",
        "reason": reason,
        "downlink_mbps": None,
        "cap_mbps": round(float(floor_mbps), 1),
        "cap_bytes_per_sec": cap_bytes_per_sec,
    }
    if partial:
        probe["partial"] = True
    if command:
        probe["command"] = command
    return probe


def _parse_networkquality_output(
    output: str, *, percent: float, floor_mbps: int
) -> dict[str, Any] | None:
    text = (output or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        throughput_bps = _coerce_float(payload.get("dl_throughput"))
        if throughput_bps and throughput_bps > 0:
            downlink_mbps = round(throughput_bps / _BITS_PER_MEGABIT, 1)
            cap_bytes_per_sec = _cap_bytes_per_sec_from_mbps(
                downlink_mbps, percent, floor_mbps
            )
            probe: dict[str, Any] = {
                "source": "networkquality",
                "reason": "probe_complete",
                "downlink_mbps": downlink_mbps,
                "cap_mbps": _cap_mbps_from_bytes_per_sec(cap_bytes_per_sec),
                "cap_bytes_per_sec": cap_bytes_per_sec,
            }
            ul_throughput_bps = _coerce_float(payload.get("ul_throughput"))
            if ul_throughput_bps and ul_throughput_bps > 0:
                probe["uplink_mbps"] = round(ul_throughput_bps / _BITS_PER_MEGABIT, 1)
            responsiveness = _coerce_float(payload.get("dl_responsiveness"))
            if responsiveness is None:
                responsiveness = _coerce_float(payload.get("responsiveness"))
            if responsiveness is not None:
                probe["responsiveness_rpm"] = round(responsiveness, 1)
            interface_name = payload.get("interface_name")
            if isinstance(interface_name, str) and interface_name:
                probe["interface_name"] = interface_name
            return probe
    match = re.search(
        r"Downlink(?:\s+capacity)?:\s+([\d.]+)\s+Mbps", text, re.IGNORECASE
    )
    if match:
        downlink_mbps = float(match.group(1))
        cap_bytes_per_sec = _cap_bytes_per_sec_from_mbps(
            downlink_mbps, percent, floor_mbps
        )
        return {
            "source": "networkquality",
            "reason": "probe_complete",
            "downlink_mbps": round(downlink_mbps, 1),
            "cap_mbps": _cap_mbps_from_bytes_per_sec(cap_bytes_per_sec),
            "cap_bytes_per_sec": cap_bytes_per_sec,
            "command_mode": "text_fallback",
        }
    return None


def probe_bandwidth(percent: float = 0.8, floor_mbps: int = 2) -> dict[str, Any]:
    cmd = _core()._find_networkquality()
    if not cmd:
        return _default_bandwidth_probe(
            floor_mbps=floor_mbps, reason="probe_unavailable"
        )

    probe_cmd = [cmd, "-u", "-c", "-s", "-M", str(_NETWORKQUALITY_MAX_RUNTIME)]
    command = " ".join(probe_cmd)
    try:
        completed = subprocess.run(
            probe_cmd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_NETWORKQUALITY_TIMEOUT,
        )
        parsed = _parse_networkquality_output(
            completed.stdout or "", percent=percent, floor_mbps=floor_mbps
        )
        if parsed:
            parsed["command"] = command
            return parsed
        return _default_bandwidth_probe(
            floor_mbps=floor_mbps, reason="probe_no_parse", command=command
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        parsed = _parse_networkquality_output(
            out, percent=percent, floor_mbps=floor_mbps
        )
        if parsed:
            parsed["reason"] = "probe_timeout_partial_capture"
            parsed["partial"] = True
            parsed["command"] = command
            return parsed
        return _default_bandwidth_probe(
            floor_mbps=floor_mbps,
            reason="probe_timeout_no_parse",
            partial=True,
            command=command,
        )
    except Exception:
        return _default_bandwidth_probe(
            floor_mbps=floor_mbps, reason="probe_error", command=command
        )


def _should_probe_bandwidth(state: dict[str, Any], now: float | None = None) -> bool:
    if now is None:
        now = time.time()
    last_probe_at = state.get("last_bandwidth_probe_at")
    try:
        last_probe_ts = float(last_probe_at)
    except (TypeError, ValueError):
        return True
    return (now - last_probe_ts) >= _NETWORKQUALITY_PROBE_INTERVAL


def _apply_bandwidth_probe(
    *,
    port: int = 6800,
    state: dict[str, Any] | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], float, int]:
    core = _core()
    if state is None:
        state = core.load_state()
    config = bandwidth_config()
    interval = config["probe_interval_seconds"]
    use_pct = config["down_use_percent"]
    now = time.time()
    probe = state.get("last_bandwidth_probe")
    needs_probe = (
        force
        or not isinstance(probe, dict)
        or core._should_probe_bandwidth(state, now=now)
    )
    if needs_probe:
        probe = core.probe_bandwidth(percent=use_pct, floor_mbps=1)
        probe["interval_seconds"] = interval
        down_cap = _apply_free_bandwidth_cap(
            probe.get("downlink_mbps"),
            config["down_free_percent"],
            config["down_free_absolute_mbps"],
        )
        probe["down_cap_mbps"] = down_cap
        if down_cap is not None:
            probe["cap_mbps"] = down_cap
            probe["cap_bytes_per_sec"] = max(1, int(down_cap * _BYTES_PER_MEGABIT))
        up_cap = _apply_free_bandwidth_cap(
            probe.get("uplink_mbps"),
            config["up_free_percent"],
            config["up_free_absolute_mbps"],
        )
        probe["up_cap_mbps"] = up_cap
        state["last_bandwidth_probe"] = probe
        state["last_bandwidth_probe_at"] = now
    elif isinstance(probe, dict) and "interval_seconds" not in probe:
        probe = dict(probe)
        probe["interval_seconds"] = interval
        state["last_bandwidth_probe"] = probe
    cap_mbps = float(probe.get("cap_mbps") or 0) if isinstance(probe, dict) else 0.0
    cap_bytes_per_sec = int(
        (probe or {}).get("cap_bytes_per_sec")
        or _cap_bytes_per_sec_from_mbps(cap_mbps if cap_mbps > 0 else 2.0, 1.0, 1)
    )
    if needs_probe:
        core.save_state(state)
        before_bandwidth = core.aria2_current_bandwidth(port=port)
        try:
            core.aria2_set_max_overall_download_limit(cap_bytes_per_sec, port=port)
        except Exception:
            pass
        up_cap = int(float((probe or {}).get("up_cap_mbps") or 0) * _BYTES_PER_MEGABIT)
        if up_cap > 0:
            try:
                core.aria2_set_max_overall_upload_limit(up_cap, port=port)
            except Exception:
                pass
        core.record_action(
            action="probe",
            target="bandwidth",
            outcome="changed"
            if (probe or {}).get("source") == "networkquality"
            else "unchanged",
            reason=(probe or {}).get("reason", (probe or {}).get("source", "default")),
            before={"cap": before_bandwidth},
            after={
                "probe": probe,
                "cap_mbps": cap_mbps,
                "cap_bytes_per_sec": cap_bytes_per_sec,
            },
            detail=probe if isinstance(probe, dict) else None,
        )
    return (probe if isinstance(probe, dict) else {}), cap_mbps, cap_bytes_per_sec
