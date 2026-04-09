from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

from ..api import load_queue
from .helpers import _error_payload


def get_torrents(h: object, parsed: object) -> None:
    items = load_queue()
    seeds = []
    for item in items:
        if item.get("distribute_status") == "seeding" and item.get(
            "distribute_infohash"
        ):
            seeds.append(
                {
                    "infohash": item["distribute_infohash"],
                    "name": item.get("output")
                    or item.get("url", "").split("/")[-1].split("?")[0],
                    "url": item.get("url"),
                    "seed_gid": item.get("distribute_seed_gid"),
                    "torrent_url": f"/api/torrents/{item['distribute_infohash']}.torrent",
                    "started_at": item.get("distribute_started_at"),
                    "item_id": item.get("id"),
                }
            )
    h._send_json({"torrents": seeds, "count": len(seeds)})


def get_torrent_file(h: object, parsed: object) -> None:
    path = urlparse(h.path).path
    infohash = path.split("/")[-1].removesuffix(".torrent")
    items = load_queue()
    for item in items:
        if item.get("distribute_infohash") == infohash:
            torrent_path = item.get("distribute_torrent_path")
            if torrent_path and Path(torrent_path).is_file():
                body = Path(torrent_path).read_bytes()
                h.send_response(HTTPStatus.OK)
                h.send_header("Content-Type", "application/x-bittorrent")
                h.send_header("Content-Length", str(len(body)))
                h.send_header("Access-Control-Allow-Origin", "*")
                h.end_headers()
                h.wfile.write(body)
                return
    h._send_json(_error_payload("not_found", "torrent not found"), status=404)


def post_torrent_stop(h: object, payload: object, path: str) -> None:
    """Stop seeding a specific torrent by infohash."""
    if not isinstance(payload, dict):
        h._send_json(
            _error_payload("invalid_payload", "expected {infohash}"), status=400
        )
        return
    infohash = str(payload.get("infohash", "")).strip()
    if not infohash:
        h._send_json(_error_payload("invalid_payload", "infohash required"), status=400)
        return
    from ..core import load_queue, save_queue, aria2_remove, record_action

    items = load_queue()
    found = False
    for item in items:
        if (
            item.get("distribute_infohash") == infohash
            and item.get("distribute_status") == "seeding"
        ):
            seed_gid = item.get("distribute_seed_gid")
            if seed_gid:
                try:
                    aria2_remove(seed_gid)
                except Exception:
                    pass
            torrent_path = item.get("distribute_torrent_path")
            if torrent_path:
                try:
                    import os

                    os.remove(torrent_path)
                except Exception:
                    pass
            item["distribute_status"] = "stopped"
            item.pop("distribute_seed_gid", None)
            found = True
            record_action(
                action="seed_stopped",
                target="queue_item",
                outcome="changed",
                reason="user_stop_seed",
                before={},
                after={"item_id": item.get("id"), "infohash": infohash},
                detail={"item_id": item.get("id"), "infohash": infohash},
            )
            break
    if found:
        save_queue(items)
        h._invalidate_status_cache()
        h._send_json({"ok": True, "infohash": infohash, "status": "stopped"})
    else:
        h._send_json(
            _error_payload("not_found", f"no active seed for {infohash}"), status=404
        )
