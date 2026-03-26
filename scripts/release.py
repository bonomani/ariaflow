#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "src" / "aria_queue" / "__init__.py"
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:a(\d+))?")


def read_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not find project version in pyproject.toml")
    return match.group(1)


def read_package_version() -> str:
    text = PACKAGE_INIT.read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not find package version in src/aria_queue/__init__.py")
    return match.group(1)


def parse_version(version: str) -> tuple[int, int, int, int | None]:
    match = re.fullmatch(VERSION_RE, version)
    if not match:
        raise SystemExit(f"Unsupported version format: {version!r}")
    major, minor, patch, alpha = match.groups()
    return int(major), int(minor), int(patch), int(alpha) if alpha is not None else None


def version_to_tag(version: str) -> str:
    major, minor, patch, alpha = parse_version(version)
    if alpha is not None:
        raise SystemExit(f"Release versions must be stable semver, got: {version!r}")
    return f"v{major}.{minor}.{patch}"


def next_release_version(version: str) -> str:
    major, minor, patch, alpha = parse_version(version)
    if alpha is not None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch + 1}"


def write_version(version: str) -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    pyproject = re.sub(r'^version = "[^"]+"$', f'version = "{version}"', pyproject, flags=re.MULTILINE)
    PYPROJECT.write_text(pyproject, encoding="utf-8")

    init_py = PACKAGE_INIT.read_text(encoding="utf-8")
    init_py = re.sub(r'^__version__ = "[^"]+"$', f'__version__ = "{version}"', init_py, flags=re.MULTILINE)
    PACKAGE_INIT.write_text(init_py, encoding="utf-8")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def git_output(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True)
    return completed.stdout.strip()


def ensure_clean_tree(allow_dirty: bool) -> None:
    if allow_dirty:
        return
    status = git_output("status", "--porcelain")
    if status:
        raise SystemExit("Working tree is dirty. Commit or stash changes, or pass --allow-dirty.")


def tag_exists(tag: str) -> bool:
    local = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if local.returncode == 0:
        return True
    remote = subprocess.run(["git", "ls-remote", "--tags", "origin", tag], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return bool(remote.stdout.strip())


def run_py_compile() -> None:
    files = (
        sorted(glob.glob(str(ROOT / "src" / "aria_queue" / "*.py")))
        + sorted(glob.glob(str(ROOT / "tests" / "*.py")))
        + [str(ROOT / "scripts" / "release.py"), str(ROOT / "scripts" / "homebrew_formula.py")]
    )
    run(["python3", "-m", "py_compile", *files])


def build_plan(current: str, next_version: str, tag: str, push: bool, run_tests: bool, allow_dirty: bool) -> list[str]:
    return [
        f"current version: {current}",
        f"next version: {next_version}",
        f"tag: {tag}",
        f"tests: {'run' if run_tests else 'skip'}",
        f"dirty tree: {'allowed' if allow_dirty else 'not allowed'}",
        f"push: {'yes' if push else 'no'}",
        "write pyproject.toml and src/aria_queue/__init__.py",
        f"commit: Release {next_version}",
        f"tag: {tag}",
        "if push: git push origin main --tags",
        "GitHub Actions will publish the release and update the Homebrew tap formula",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bump ariaflow, tag a release, and push it.")
    parser.add_argument("--version", help="Set an explicit stable package version like 0.1.2.")
    parser.add_argument("--no-tests", action="store_true", help="Skip local tests before committing.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted changes before releasing.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned release steps and exit.")
    parser.add_argument("--push", action="store_true", help="Push main and tags after committing.")
    args = parser.parse_args()

    current = read_version()
    package_version = read_package_version()
    if current != package_version:
        raise SystemExit(f"Version files disagree: pyproject.toml={current!r}, __init__.py={package_version!r}")

    next_version = args.version or next_release_version(current)
    _, _, _, next_alpha = parse_version(next_version)
    if next_alpha is not None:
        raise SystemExit(f"Release versions must be stable semver, got: {next_version!r}")

    tag = version_to_tag(next_version)
    if tag_exists(tag):
        raise SystemExit(f"Tag already exists: {tag}")
    ensure_clean_tree(args.allow_dirty)

    plan = build_plan(
        current=current,
        next_version=next_version,
        tag=tag,
        push=args.push,
        run_tests=not args.no_tests,
        allow_dirty=args.allow_dirty,
    )
    if args.dry_run:
        print("\n".join(plan))
        print("Dry run only; no files changed.")
        return 0

    if not args.no_tests:
        run_py_compile()
        run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"])

    write_version(next_version)
    run(["git", "add", "pyproject.toml", "src/aria_queue/__init__.py"])
    run(["git", "commit", "-m", f"Release {next_version}"])
    run(["git", "tag", tag])

    if args.push:
        run(["git", "push", "origin", "main"])
        run(["git", "push", "origin", tag])
    else:
        print(f"Tagged {tag}. Push with: git push origin main && git push origin {tag}")

    print(f"Prepared release tag: {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
