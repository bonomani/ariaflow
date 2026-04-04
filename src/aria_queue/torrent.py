"""Private torrent creation for internal distribution.

Creates .torrent files with private=1 flag and internal tracker URL.
Uses mktorrent CLI if available, falls back to pure-Python bencode.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _mktorrent_path() -> str | None:
    return shutil.which("mktorrent")


def _bencode(obj: Any) -> bytes:
    """Minimal bencode encoder for torrent creation."""
    if isinstance(obj, int):
        return f"i{obj}e".encode()
    if isinstance(obj, bytes):
        return f"{len(obj)}:".encode() + obj
    if isinstance(obj, str):
        encoded = obj.encode("utf-8")
        return f"{len(encoded)}:".encode() + encoded
    if isinstance(obj, list):
        return b"l" + b"".join(_bencode(i) for i in obj) + b"e"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0].encode() if isinstance(kv[0], str) else kv[0])
        return b"d" + b"".join(
            _bencode(k) + _bencode(v) for k, v in items
        ) + b"e"
    raise TypeError(f"Cannot bencode {type(obj)}")


def _compute_piece_size(file_size: int) -> int:
    """Choose piece size: target ~1000-2000 pieces."""
    if file_size <= 0:
        return 256 * 1024
    target_pieces = 1500
    raw = file_size // target_pieces
    # Round up to nearest power of 2, min 256KB, max 16MB
    power = max(18, min(24, math.ceil(math.log2(max(raw, 1)))))
    return 1 << power


def create_private_torrent(
    file_path: str | Path,
    tracker_url: str,
    comment: str = "",
) -> dict[str, Any]:
    """Create a private .torrent for a file.

    Returns dict with:
        torrent_path: path to .torrent file
        torrent_b64: base64-encoded .torrent content
        infohash: SHA1 of the info dict
        piece_count: number of pieces
        file_size: size in bytes
    """
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_size = file_path.stat().st_size
    if file_size == 0:
        raise ValueError("Cannot create torrent from empty file")

    torrent_dir = file_path.parent
    torrent_path = torrent_dir / (file_path.name + ".torrent")

    # Try mktorrent first (faster, handles large files well)
    if _mktorrent_path():
        return _create_with_mktorrent(
            file_path, torrent_path, tracker_url, comment, file_size
        )

    # Fallback: pure Python
    return _create_with_python(
        file_path, torrent_path, tracker_url, comment, file_size
    )


def _create_with_mktorrent(
    file_path: Path,
    torrent_path: Path,
    tracker_url: str,
    comment: str,
    file_size: int,
) -> dict[str, Any]:
    cmd = [
        _mktorrent_path() or "mktorrent",
        "-p",  # private
        "-a", tracker_url,
        "-o", str(torrent_path),
    ]
    if comment:
        cmd.extend(["-c", comment])
    cmd.append(str(file_path))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"mktorrent failed: {result.stderr.strip()}")

    torrent_bytes = torrent_path.read_bytes()
    infohash = _extract_infohash(torrent_bytes)
    piece_size = _compute_piece_size(file_size)
    piece_count = math.ceil(file_size / piece_size)

    return {
        "torrent_path": str(torrent_path),
        "torrent_b64": base64.b64encode(torrent_bytes).decode("ascii"),
        "infohash": infohash,
        "piece_count": piece_count,
        "file_size": file_size,
    }


def _create_with_python(
    file_path: Path,
    torrent_path: Path,
    tracker_url: str,
    comment: str,
    file_size: int,
) -> dict[str, Any]:
    piece_size = _compute_piece_size(file_size)
    pieces = b""
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(piece_size)
            if not chunk:
                break
            pieces += hashlib.sha1(chunk).digest()

    info: dict[str, Any] = {
        "name": file_path.name,
        "piece length": piece_size,
        "pieces": pieces,
        "length": file_size,
        "private": 1,
    }

    torrent: dict[str, Any] = {
        "announce": tracker_url,
        "info": info,
    }
    if comment:
        torrent["comment"] = comment
    torrent["created by"] = "ariaflow"

    info_bencoded = _bencode(info)
    infohash = hashlib.sha1(info_bencoded).hexdigest()

    torrent_bytes = _bencode(torrent)
    torrent_path.write_bytes(torrent_bytes)

    return {
        "torrent_path": str(torrent_path),
        "torrent_b64": base64.b64encode(torrent_bytes).decode("ascii"),
        "infohash": infohash,
        "piece_count": math.ceil(file_size / piece_size),
        "file_size": file_size,
    }


def _extract_infohash(torrent_bytes: bytes) -> str:
    """Extract infohash from raw .torrent bytes by finding the info dict."""
    # Find b"4:infod" pattern and extract until matching "e"
    marker = b"4:infod"
    idx = torrent_bytes.find(marker)
    if idx < 0:
        raise ValueError("Cannot find info dict in torrent")
    info_start = idx + len(b"4:info")
    # Simple depth-based extraction: find matching 'e' for the 'd'
    depth = 0
    i = info_start
    while i < len(torrent_bytes):
        c = torrent_bytes[i:i+1]
        if c == b"d" or c == b"l":
            depth += 1
            i += 1
        elif c == b"e":
            depth -= 1
            if depth == 0:
                info_bytes = torrent_bytes[info_start:i+1]
                return hashlib.sha1(info_bytes).hexdigest()
            i += 1
        elif c == b"i":
            # integer: i<number>e
            end = torrent_bytes.index(b"e", i)
            i = end + 1
        elif c and c[0:1].isdigit():
            # string: <len>:<data>
            colon = torrent_bytes.index(b":", i)
            length = int(torrent_bytes[i:colon])
            i = colon + 1 + length
        else:
            i += 1
    raise ValueError("Malformed torrent: info dict not closed")
