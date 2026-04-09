"""Response schemas for OpenAPI generation.

Single source of truth for response field types per endpoint.
Used by scripts/gen_openapi.py to emit explicit properties in openapi.yaml.
"""

from __future__ import annotations

# Schema format: "{METHOD} {path}" -> dict of {field_name: {type: str, nullable?: bool, description?: str}}
# Types: "string", "integer", "number", "boolean", "object", "array"
# Use "object" for nested dicts, "array" for lists. For arrays, add "items": {...} if known.
#
# Every response automatically gets `_schema` and `_request_id` injected by
# webapp._send_json, so each schema here includes those two fields.

_META: dict[str, dict] = {
    "_schema": {"type": "string"},
    "_request_id": {"type": "string"},
}

# UCC envelope shape produced by install.ucc_envelope(). Reused across the
# /api/lifecycle per-target entries via the named UccEnvelope component
# defined in src/ariaflow_server/openapi.yaml. Using a $ref keeps the generated
# spec compact and avoids copy/paste drift.
_UCC_ENVELOPE: dict = {"$ref": "#/components/schemas/UccEnvelope"}


RESPONSE_SCHEMAS: dict[str, dict[str, dict]] = {
    # ── meta ──────────────────────────────────────────────────────────────
    "GET /api/health": {
        "status": {"type": "string"},
        "version": {"type": "string"},
        "disk_usage_percent": {"type": "number"},
        "disk_ok": {"type": "boolean"},
        "requests_total": {"type": "integer"},
        "bytes_sent_total": {"type": "integer"},
        "bytes_received_total": {"type": "integer"},
        "errors_total": {"type": "integer"},
        "uptime_seconds": {"type": "number"},
        "started_at": {"type": "string"},
        "sse_clients": {"type": "integer"},
        **_META,
    },
    "GET /api": {
        "name": {"type": "string"},
        "version": {"type": "string"},
        "docs": {"type": "string"},
        "openapi": {"type": "string"},
        "endpoints": {"type": "object"},
        **_META,
    },
    "GET /api/tests": {
        "ok": {"type": "boolean"},
        "returncode": {"type": "integer", "nullable": True},
        "stdout": {"type": "string", "nullable": True},
        "stderr": {"type": "string", "nullable": True},
        "error": {"type": "string", "nullable": True},
        "message": {"type": "string", "nullable": True},
        **_META,
    },
    "GET /api/log": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "target": {"type": "string"},
                    "outcome": {"type": "string"},
                    "observation": {"type": "string"},
                    "reason": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "session_id": {"type": "string", "nullable": True},
                    "observed_before": {"type": "object", "nullable": True},
                    "observed_after": {"type": "object", "nullable": True},
                    "detail": {"type": "object", "nullable": True},
                },
            },
        },
        **_META,
    },
    # /api/docs and /api/openapi.yaml return non-JSON (HTML/YAML) and are not
    # listed here. /api/events is a text/event-stream (SSE) and not JSON either.
    # ── scheduler ─────────────────────────────────────────────────────────
    "GET /api/scheduler": {
        "status": {"type": "string"},
        "running": {"type": "boolean"},
        "paused": {"type": "boolean"},
        "session_id": {"type": "string", "nullable": True},
        "session_started_at": {"type": "string", "nullable": True},
        "session_closed_at": {"type": "string", "nullable": True},
        "_rev": {"type": "integer"},
        **_META,
    },
    # ── bandwidth ─────────────────────────────────────────────────────────
    "GET /api/bandwidth": {
        "config": {"type": "object"},
        "current_limit": {"type": "object", "nullable": True},
        "last_probe": {
            "type": "object",
            "nullable": True,
            "properties": {
                "source": {"type": "string"},
                "reason": {"type": "string", "nullable": True},
                "interface_name": {"type": "string", "nullable": True},
                "downlink_mbps": {"type": "number", "nullable": True},
                "uplink_mbps": {"type": "number", "nullable": True},
                "down_cap_mbps": {"type": "number", "nullable": True},
                "up_cap_mbps": {"type": "number", "nullable": True},
                "cap_mbps": {"type": "number", "nullable": True},
                "cap_bytes_per_sec": {"type": "integer", "nullable": True},
                "responsiveness_rpm": {"type": "number", "nullable": True},
                "command": {"type": "string", "nullable": True},
                "partial": {"type": "boolean", "nullable": True},
            },
        },
        "last_probe_at": {"type": "string", "nullable": True},
        "interface": {"type": "string", "nullable": True},
        "downlink_mbps": {"type": "number", "nullable": True},
        "uplink_mbps": {"type": "number", "nullable": True},
        "down_cap_mbps": {"type": "number", "nullable": True},
        "up_cap_mbps": {"type": "number", "nullable": True},
        "cap_bytes_per_sec": {"type": "integer", "nullable": True},
        "responsiveness_rpm": {"type": "number", "nullable": True},
        **_META,
    },
    # bandwidth probe is the only POST currently in RESPONSE_SCHEMAS — the
    # generator already supports any METHOD prefix, this just fills it in.
    "POST /api/bandwidth/probe": {
        "ok": {"type": "boolean"},
        "probe": {"type": "object"},
        "config": {"type": "object"},
        "interface": {"type": "string", "nullable": True},
        "downlink_mbps": {"type": "number", "nullable": True},
        "uplink_mbps": {"type": "number", "nullable": True},
        "down_cap_mbps": {"type": "number", "nullable": True},
        "up_cap_mbps": {"type": "number", "nullable": True},
        "cap_bytes_per_sec": {"type": "integer", "nullable": True},
        "responsiveness_rpm": {"type": "number", "nullable": True},
        "source": {"type": "string", "nullable": True},
        **_META,
    },
    # ── downloads / status ────────────────────────────────────────────────
    "GET /api/status": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/QueueItem"},
        },
        "state": {"type": "object"},
        "summary": {"type": "object"},
        "aria2": {"$ref": "#/components/schemas/Aria2Health"},
        "bandwidth": {"type": "object", "nullable": True},
        "_rev": {"type": "integer"},
        "ariaflow-server": {"$ref": "#/components/schemas/AriaflowHealth"},
        "discovery": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "backend": {"type": "string", "nullable": True},
            },
        },
        "active": {"$ref": "#/components/schemas/ActiveTransfer"},
        "actives": {
            "type": "array",
            "nullable": True,
            "items": {"type": "object"},
        },
        "filtered": {"type": "boolean", "nullable": True},
        "health": {"type": "object"},
        **_META,
    },
    "GET /api/downloads/archive": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/QueueItem"},
        },
        **_META,
    },
    "GET /api/downloads/{id}/files": {
        "ok": {"type": "boolean"},
        "item_id": {"type": "string", "nullable": True},
        "gid": {"type": "string", "nullable": True},
        "files": {"type": "array", "items": {"type": "object"}, "nullable": True},
        "error": {"type": "string", "nullable": True},
        "message": {"type": "string", "nullable": True},
        **_META,
    },
    # ── torrents ──────────────────────────────────────────────────────────
    "GET /api/torrents": {
        "torrents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "infohash": {"type": "string"},
                    "name": {"type": "string"},
                    "url": {"type": "string", "nullable": True},
                    "seed_gid": {"type": "string", "nullable": True},
                    "torrent_url": {"type": "string"},
                    "started_at": {"type": "string", "nullable": True},
                    "item_id": {"type": "string", "nullable": True},
                },
            },
        },
        "count": {"type": "integer"},
        **_META,
    },
    "GET /api/torrents/{infohash}.torrent": {
        "error": {"type": "string", "nullable": True},
        "message": {"type": "string", "nullable": True},
        **_META,
    },
    # ── peers ─────────────────────────────────────────────────────────────
    "GET /api/peers": {
        "peers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "instance": {"type": "string"},
                    "host": {"type": "string"},
                    "port": {"type": "integer"},
                    "path": {"type": "string"},
                    "tls": {"type": "boolean"},
                    "base_url": {"type": "string"},
                    "last_seen": {"type": "number"},
                    "status": {"type": "string"},
                },
            },
        },
        **_META,
    },
    # ── declaration (UIC) ─────────────────────────────────────────────────
    # Top-level shape: meta / uic / targets — load_declaration() returns the
    # raw DEFAULT_DECLARATION dict from contracts.py with no flattening.
    "GET /api/declaration": {
        "meta": {
            "type": "object",
            "properties": {
                "contract": {"type": "string"},
                "version": {"type": "string"},
            },
        },
        "uic": {
            "type": "object",
            "properties": {
                "gates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "class": {"type": "string"},
                            "blocking": {"type": "string"},
                        },
                    },
                },
                "preferences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "object", "nullable": True},
                            "options": {"type": "array"},
                            "rationale": {"type": "string"},
                        },
                    },
                },
                "policies": {"type": "array", "items": {"type": "object"}},
            },
        },
        "targets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                },
            },
        },
        **_META,
    },
    # ── aria2 ─────────────────────────────────────────────────────────────
    "GET /api/aria2/get_global_option": {
        # aria2 returns an arbitrary key/value map of option strings
        **_META,
    },
    "GET /api/aria2/get_option": {
        "ok": {"type": "boolean", "nullable": True},
        "gid": {"type": "string", "nullable": True},
        "options": {"type": "object", "nullable": True},
        "error": {"type": "string", "nullable": True},
        "message": {"type": "string", "nullable": True},
        **_META,
    },
    "GET /api/aria2/option_tiers": {
        "managed": {"type": "array", "items": {"type": "string"}},
        "safe": {"type": "array", "items": {"type": "string"}},
        "unsafe_enabled": {"type": "boolean"},
        **_META,
    },
    # ── lifecycle ─────────────────────────────────────────────────────────
    # Each per-target entry is a UCC envelope (meta + result) produced by
    # ucc_record() in install.py. Session fields are merged in by
    # routes/lifecycle.py::_lifecycle_payload().
    "GET /api/lifecycle": {
        "ariaflow-server": _UCC_ENVELOPE,
        "aria2": _UCC_ENVELOPE,
        "networkquality": _UCC_ENVELOPE,
        "aria2-launchd": _UCC_ENVELOPE,
        "session_id": {"type": "string", "nullable": True},
        "session_started_at": {"type": "string", "nullable": True},
        "session_last_seen_at": {"type": "string", "nullable": True},
        "session_closed_at": {"type": "string", "nullable": True},
        "session_closed_reason": {"type": "string", "nullable": True},
        **_META,
    },
    # ── sessions ──────────────────────────────────────────────────────────
    "GET /api/sessions": {
        "sessions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "started_at": {"type": "string", "nullable": True},
                    "closed_at": {"type": "string", "nullable": True},
                    "closed_reason": {"type": "string", "nullable": True},
                    "items_total": {"type": "integer", "nullable": True},
                },
            },
        },
        **_META,
    },
    "GET /api/sessions/stats": {
        "session_id": {"type": "string", "nullable": True},
        "started_at": {"type": "string", "nullable": True},
        "items_total": {"type": "integer", "nullable": True},
        "items_active": {"type": "integer", "nullable": True},
        "items_archived": {"type": "integer", "nullable": True},
        "items_done": {"type": "integer", "nullable": True},
        "items_error": {"type": "integer", "nullable": True},
        "items_queued": {"type": "integer", "nullable": True},
        "items_downloading": {"type": "integer", "nullable": True},
        "items_paused": {"type": "integer", "nullable": True},
        "bytes_completed": {"type": "integer", "nullable": True},
        **_META,
    },
}
