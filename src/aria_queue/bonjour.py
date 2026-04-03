from __future__ import annotations

import os
import platform
import shutil
import subprocess
from contextlib import contextmanager
from typing import Iterator


def _dns_sd_path() -> str | None:
    return shutil.which("dns-sd")


def bonjour_available() -> bool:
    return platform.system() == "Darwin" and _dns_sd_path() is not None


@contextmanager
def advertise_http_service(
    *, role: str, port: int, path: str, product: str, version: str
) -> Iterator[None]:
    if not bonjour_available():
        yield
        return
    host = os.uname().nodename.split(".")[0] or "localhost"
    cmd = [
        _dns_sd_path() or "dns-sd",
        "-R",
        f"ariaflow {role} {host} {port}",
        "_http._tcp",
        "local",
        str(port),
        f"role={role}",
        f"path={path}",
        f"product={product}",
        f"version={version}",
        "proto=http",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield
    finally:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        except Exception:
            pass
