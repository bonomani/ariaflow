from __future__ import annotations

from ..api import (
    bandwidth_status,
    manual_probe,
)


def get_bandwidth(h: object, parsed: object) -> None:
    h._send_json(bandwidth_status())


def post_bandwidth_probe(h: object, payload: object, path: str) -> None:
    result = manual_probe()
    h._invalidate_status_cache()
    h._send_json(result)
