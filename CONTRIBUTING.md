# Contributing to ariaflow-server

## Setup

```bash
git clone https://github.com/bonomani/ariaflow-server.git
cd ariaflow-server
pip install -e .
```

Python >= 3.10 required. Zero dependencies.

## Common Commands

```bash
make test       # run all tests
make check      # tests + naming convention check
make lint       # ruff linter
make format     # ruff formatter
make docs       # regenerate auto-generated docs
make clean      # remove caches and temp files
```

Or directly:

```bash
python -m pytest tests/ -x -q     # run tests
python scripts/gen_all_variables.py --check  # naming compliance
```

## Code Style

- **Python:** PEP 8, enforced by `ruff`
- **Naming:** All snake_case. aria2-facing functions use `aria2_` prefix. See `tests/test_naming_conventions.py` for 11 automated rules.
- **Types:** All functions must have type annotations (parameters + return type)
- **No abbreviations** in public function names

## Project Structure

```
src/aria_queue/
  storage.py      — file I/O, locking, paths
  state.py        — state, sessions, action log, archive
  aria2_rpc.py    — aria_rpc + 36 aria2_* RPC wrappers + 12 helpers
  bandwidth.py    — probe, apply, networkQuality
  queue_ops.py    — QueueItem, CRUD, per-item operations
  transfers.py    — discover, pause/resume all, preferences
  reconcile.py    — reconcile, deduplicate, cleanup
  scheduler.py    — process_queue, start/stop
  core.py         — re-export hub (backward compat)
  webapp.py       — HTTP API server
  contracts.py    — UIC gates, UCC declaration
  cli.py          — CLI entry point
```

## Commits

- One logical change per commit
- Descriptive message: what and why, not how
- Run `make check` before committing
- Don't use `git add -A` (risk of committing generated files)

## Pull Requests

- Branch from `main`
- All tests must pass
- Naming convention check must pass
- Update docs if behavior changes

## Release

See [`docs/RELEASE.md`](./docs/RELEASE.md). Normal flow:

```bash
python3 scripts/publish.py plan   # preview
python3 scripts/publish.py push   # push + auto-release
```

## Plan

All planned work lives in [`docs/PLAN.md`](./docs/PLAN.md) — one file, never separate plan files. Read it before starting work.
