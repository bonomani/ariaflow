from __future__ import annotations


def get_peers(h: object, parsed: object) -> None:
    from ..discovery import list_peers

    h._send_json({"peers": list_peers()})
