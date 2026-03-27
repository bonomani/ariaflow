#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = "bonomani/ariaflow"
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


def current_branch() -> str:
    return git_output("rev-parse", "--abbrev-ref", "HEAD")


def ensure_main_branch() -> None:
    branch = current_branch()
    if branch != "main":
        raise SystemExit(f"Run this helper from main. Current branch: {branch}")


def push_main_with_rebase(max_attempts: int = 3) -> None:
    ensure_main_branch()
    ensure_clean_tree(False)
    for attempt in range(max_attempts):
        pushed = subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=False)
        if pushed.returncode == 0:
            return
        if attempt == max_attempts - 1:
            raise SystemExit("Unable to push origin/main after rebase retries")
        run(["git", "pull", "--rebase", "origin", "main"])


def dispatch_release(version: str) -> None:
    gh = shutil.which("gh")
    if not gh:
        raise SystemExit("gh CLI is required to trigger an explicit release")
    run([gh, "workflow", "run", "release.yml", "-R", REPO, "--ref", "main", "-f", f"version={version}"])


def run_py_compile() -> None:
    files = (
        sorted(glob.glob(str(ROOT / "src" / "aria_queue" / "*.py")))
        + sorted(glob.glob(str(ROOT / "tests" / "*.py")))
        + sorted(glob.glob(str(ROOT / "tests" / "**" / "*.py"), recursive=True))
        + [str(ROOT / "scripts" / "publish.py"), str(ROOT / "scripts" / "homebrew_formula.py")]
    )
    run(["python3", "-m", "py_compile", *files])


def build_plan(action: str, current: str, next_version: str | None, tag: str | None, run_tests: bool, allow_dirty: bool) -> list[str]:
    if action == "push":
        return [
            "rebase-safe main publish helper",
            f"current version: {current}",
            "requested version: none",
            f"tests: {'run' if run_tests else 'skip'}",
            f"dirty tree: {'allowed' if allow_dirty else 'not allowed'}",
            "action: push",
            "no version bump",
            "no local tag",
            "git push origin main with pull --rebase retry",
        ]
    if action == "release":
        return [
            "explicit release dispatch helper",
            f"current version: {current}",
            f"requested version: {next_version}",
            f"tag: {tag}",
            f"tests: {'run' if run_tests else 'skip'}",
            f"dirty tree: {'allowed' if allow_dirty else 'not allowed'}",
            "action: release",
            "sync current main with rebase-safe push",
            f"trigger GitHub Actions workflow_dispatch release for {next_version}",
            "GitHub Actions will create the release commit/tag and update the Homebrew tap formula",
        ]
    return [
        "publish plan preview",
        f"current version: {current}",
        f"requested version: {next_version or 'none'}",
        f"tag: {tag or 'none'}",
        f"tests: {'run' if run_tests else 'skip'}",
        f"dirty tree: {'allowed' if allow_dirty else 'not allowed'}",
        "action: plan",
        "preview only; no files changed",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebase-safe push and explicit publish helper for ariaflow. Normal patch releases come from the CI workflow on main pushes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Preview a push or explicit release without changing anything.")
    plan_parser.add_argument("--version", help="Preview an explicit stable release like 0.1.2.")
    plan_parser.add_argument("--no-tests", action="store_true", help="Show a plan that skips local tests.")
    plan_parser.add_argument("--allow-dirty", action="store_true", help="Allow dirty trees for preview only.")

    push_parser = subparsers.add_parser("push", help="Run tests, then push main with rebase-safe sync.")
    push_parser.add_argument("--no-tests", action="store_true", help="Skip local tests before pushing.")

    release_parser = subparsers.add_parser("release", help="Run tests, push main with rebase-safe sync, then trigger an explicit GitHub release.")
    release_parser.add_argument("--version", required=True, help="Trigger an explicit stable release like 0.1.2 via workflow_dispatch.")
    release_parser.add_argument("--no-tests", action="store_true", help="Skip local tests before publishing.")

    args = parser.parse_args()

    current = read_version()
    package_version = read_package_version()
    if current != package_version:
        raise SystemExit(f"Version files disagree: pyproject.toml={current!r}, __init__.py={package_version!r}")

    ensure_main_branch()
    next_version = getattr(args, "version", None)
    tag: str | None = None
    if next_version is not None:
        _, _, _, next_alpha = parse_version(next_version)
        if next_alpha is not None:
            raise SystemExit(f"Release versions must be stable semver, got: {next_version!r}")
        tag = version_to_tag(next_version)
        if tag_exists(tag):
            raise SystemExit(f"Tag already exists: {tag}")
    allow_dirty = bool(getattr(args, "allow_dirty", False))
    if args.command == "plan":
        ensure_clean_tree(allow_dirty)
    else:
        ensure_clean_tree(False)

    plan = build_plan(
        action=args.command,
        current=current,
        next_version=next_version,
        tag=tag,
        run_tests=not args.no_tests,
        allow_dirty=allow_dirty,
    )
    if args.command == "plan":
        print("\n".join(plan))
        print("Dry run only; no files changed.")
        return 0

    if not args.no_tests:
        run_py_compile()
        run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"])

    push_main_with_rebase()
    if args.command == "push":
        print("Synced origin/main with rebase-safe push.")
        return 0

    dispatch_release(next_version)
    print(f"Triggered workflow-dispatch release for {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
