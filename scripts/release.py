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
        + [str(ROOT / "scripts" / "release.py"), str(ROOT / "scripts" / "homebrew_formula.py")]
    )
    run(["python3", "-m", "py_compile", *files])


def build_plan(current: str, next_version: str | None, tag: str | None, push: bool, run_tests: bool, allow_dirty: bool) -> list[str]:
    if next_version is None:
        return [
            "rebase-safe main publish helper",
            f"current version: {current}",
            "requested version: none",
            f"tests: {'run' if run_tests else 'skip'}",
            f"dirty tree: {'allowed' if allow_dirty else 'not allowed'}",
            f"push: {'yes' if push else 'no'}",
            "no version bump",
            "no local tag",
            "if push: git push origin main with pull --rebase retry",
        ]
    return [
        "explicit release dispatch helper",
        f"current version: {current}",
        f"requested version: {next_version}",
        f"tag: {tag}",
        f"tests: {'run' if run_tests else 'skip'}",
        f"dirty tree: {'allowed' if allow_dirty else 'not allowed'}",
        f"push: {'yes' if push else 'no'}",
        "sync current main with rebase-safe push",
        f"trigger GitHub Actions workflow_dispatch release for {next_version}",
        "GitHub Actions will create the release commit/tag and update the Homebrew tap formula",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebase-safe push and explicit release helper for ariaflow. Normal patch releases come from the CI workflow on main pushes."
    )
    parser.add_argument("--version", help="Trigger an explicit stable release like 0.1.2 via workflow_dispatch.")
    parser.add_argument("--no-tests", action="store_true", help="Skip local tests before committing.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow dirty trees only for dry-run planning. Real pushes still require a clean tree.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned release steps and exit.")
    parser.add_argument("--push", action="store_true", help="Push main with rebase-safe sync. Required for real sync/release actions.")
    args = parser.parse_args()

    current = read_version()
    package_version = read_package_version()
    if current != package_version:
        raise SystemExit(f"Version files disagree: pyproject.toml={current!r}, __init__.py={package_version!r}")

    ensure_main_branch()
    next_version = args.version
    tag: str | None = None
    if next_version is not None:
        _, _, _, next_alpha = parse_version(next_version)
        if next_alpha is not None:
            raise SystemExit(f"Release versions must be stable semver, got: {next_version!r}")
        tag = version_to_tag(next_version)
        if tag_exists(tag):
            raise SystemExit(f"Tag already exists: {tag}")
    if args.push:
        ensure_clean_tree(False)
    else:
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

    if not args.push:
        raise SystemExit("Pass --push to sync main or trigger an explicit release.")

    if not args.no_tests:
        run_py_compile()
        run(["python3", "-m", "unittest", "discover", "-s", "tests", "-v"])

    push_main_with_rebase()
    if next_version is None:
        print("Synced origin/main with rebase-safe push.")
        return 0

    dispatch_release(next_version)
    print(f"Triggered workflow-dispatch release for {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
