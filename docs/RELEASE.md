# Release Process

## Quick Release

```bash
python3 scripts/publish.py plan    # preview — no side effects
python3 scripts/publish.py push    # push main + auto-release
```

The helper validates version consistency (`pyproject.toml` vs `__init__.py`), runs tests, pushes `main` with rebase retry, and lets GitHub Actions handle the rest.

## What GitHub Actions Does

On push to `main` (or `workflow_dispatch`), `.github/workflows/release.yml`:

1. Runs test suite
2. Builds source distribution
3. Creates GitHub release (stable, not draft/prerelease)
4. Updates `bonomani/homebrew-ariaflow/Formula/ariaflow.rb`

## Explicit Version Release

```bash
python3 scripts/publish.py release --version X.Y.Z
```

Triggers `workflow_dispatch` for a specific stable version.

## Helper Flags

| Flag | Effect |
|---|---|
| `plan` | Print release plan without changes |
| `push` | Push main + auto-release |
| `release --version X.Y.Z` | Dispatch explicit stable release |
| `--no-tests` | Skip local test suite |
| `plan --allow-dirty` | Preview even with uncommitted changes |

## Verification

After release:

```bash
# Check GitHub release is published (not draft)
# Check PyPI version matches
pip install ariaflow --upgrade
ariaflow --version
# Check Homebrew formula version matches
brew tap bonomani/ariaflow
brew upgrade ariaflow
ariaflow --version
```

## Prerequisites

- `ARIAFLOW_TAP_TOKEN` repo secret with write access to `bonomani/homebrew-ariaflow`
- `PYPI_TOKEN` repo secret — PyPI API token for the `ariaflow` package
- Tools: `git`, Python 3.10+, `gh`
