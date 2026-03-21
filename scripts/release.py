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


def alpha_to_tag(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", version)
    if not match:
        raise SystemExit(f"Unsupported version format: {version!r}")
    base, alpha = match.groups()
    return f"v{base}-alpha.{alpha}"


def bump_alpha(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", version)
    if not match:
        raise SystemExit(f"Unsupported version format: {version!r}")
    base, alpha = match.groups()
    return f"{base}a{int(alpha) + 1}"


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
    files = sorted(glob.glob(str(ROOT / "src" / "aria_queue" / "*.py"))) + sorted(glob.glob(str(ROOT / "tests" / "*.py"))) + [str(ROOT / "scripts" / "release.py")]
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
        f"commit: Bump version for alpha {tag.split('.')[-1]}",
        f"tag: {tag}",
        "if push: git push origin master --tags",
        "GitHub Actions will publish the prerelease and dispatch tap sync",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bump ariaflow, tag a prerelease, and push it.")
    parser.add_argument("--version", help="Set an explicit package version like 0.1.1a24.")
    parser.add_argument("--next-alpha", action="store_true", help="Auto-bump the current alpha version by one.")
    parser.add_argument("--no-tests", action="store_true", help="Skip local tests before committing.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted changes before releasing.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned release steps and exit.")
    parser.add_argument("--push", action="store_true", help="Push master and tags after committing.")
    args = parser.parse_args()

    current = read_version()
    package_version = read_package_version()
    if current != package_version:
        raise SystemExit(f"Version files disagree: pyproject.toml={current!r}, __init__.py={package_version!r}")
    if args.version and args.next_alpha:
        raise SystemExit("Use either --version or --next-alpha, not both.")

    next_version = args.version or (bump_alpha(current) if args.next_alpha else None)
    if not next_version:
        raise SystemExit("Provide --version or --next-alpha.")

    tag = alpha_to_tag(next_version)
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
    alpha = tag.split(".")[-1]
    run(["git", "commit", "-m", f"Bump version for alpha {alpha}"])
    run(["git", "tag", tag])

    if args.push:
        run(["git", "push", "origin", "master", "--tags"])
    else:
        print(f"Tagged {tag}. Push with: git push origin master --tags")

    print(f"Prepared release tag: {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
