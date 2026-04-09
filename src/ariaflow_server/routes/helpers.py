from __future__ import annotations


_ALLOWED_URL_SCHEMES = {"http", "https", "ftp", "magnet"}


def _error_payload(error: str, message: str, **detail: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": False,
        "error": error,
        "message": message,
    }
    payload.update(detail)
    return payload


def _validate_item_id(item_id: str) -> bool:
    """Check item_id looks like a UUID."""
    import re

    return bool(
        re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", item_id
        )
    )
