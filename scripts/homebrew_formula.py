#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")


def version_from_tag(tag: str) -> str:
    match = TAG_RE.fullmatch(tag)
    if not match:
        raise SystemExit(f"Expected stable tag in the form vX.Y.Z, got: {tag!r}")
    return match.group(1)


def tarball_url(tag: str) -> str:
    return f"https://github.com/bonomani/ariaflow-server/archive/refs/tags/{tag}.tar.gz"


def download_sha256(url: str) -> str:
    hasher = hashlib.sha256()
    with urlopen(url) as response:  # noqa: S310 - release workflow fetches a fixed GitHub URL
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def render_formula(*, version: str, url: str, sha256: str) -> str:
    return f"""class AriaflowServer < Formula
  desc "Sequential aria2 queue driver with adaptive bandwidth control"
  homepage "https://github.com/bonomani/ariaflow-server"
  url "{url}"
  sha256 "{sha256}"
  version "{version}"
  license "MIT"
  depends_on "python"
  depends_on "aria2"
  head "https://github.com/bonomani/ariaflow-server.git", branch: "main"

  resource "portalocker" do
    url "https://files.pythonhosted.org/packages/source/p/portalocker/portalocker-3.2.0.tar.gz"
    sha256 "1f3002956a54a8c3730586c5c77bf18fae4149e07eaf1c29fc3faf4d5a3f89ac"
  end

  def install
    python3 = "python3"
    venv = libexec/"venv"
    system python3, "-m", "venv", venv
    venv_pip = venv/"bin/pip"
    resource("portalocker").stage {{ system venv_pip, "install", "." }}

    libexec.install "src"

    (bin/"ariaflow-server").write <<~EOS
      #!/bin/bash
      exec env PYTHONPATH="#{{libexec}}/src:#{{libexec}}/venv/lib/python3.*/site-packages:${{PYTHONPATH}}" python3 -m ariaflow_server "$@"
    EOS
    chmod 0755, bin/"ariaflow-server"
  end

  service do
    run [opt_bin/"ariaflow-server", "serve", "--host", "127.0.0.1", "--port", "8000"]
    keep_alive true
    working_dir var
    log_path var/"log/ariaflow-server.log"
    error_log_path var/"log/ariaflow-server.err.log"
  end

  test do
    system bin/"ariaflow-server", "--help"
  end
end
"""


def write_formula(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Homebrew formula for ariaflow-server.")
    parser.add_argument("--tag", required=True, help="Stable release tag in the form vX.Y.Z.")
    parser.add_argument("--output", type=Path, help="Path to write the rendered formula.")
    parser.add_argument("--sha256", help="Optional precomputed checksum.")
    parser.add_argument("--dry-run", action="store_true", help="Print the rendered formula to stdout.")
    args = parser.parse_args()

    version = version_from_tag(args.tag)
    url = tarball_url(args.tag)
    sha256 = args.sha256 or download_sha256(url)
    formula = render_formula(version=version, url=url, sha256=sha256)

    if args.output:
        write_formula(args.output, formula)

    if args.dry_run or not args.output:
        sys.stdout.write(formula)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
