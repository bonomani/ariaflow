# ariaflow

Headless queue driver for `aria2c` with:

- simple URL enqueueing
- sequential execution by default, one download at a time
- pre-run bandwidth probing
- runtime bandwidth adaptation through aria2 RPC
- pluggable post-download actions
- UIC pre-flight checks
- UCC structured execution output
- TIC-style tests
Targets:

- Linux
- WSL
- macOS

## Architecture

The canonical engine architecture is documented in:

- [`ARCHITECTURE.md`](./ARCHITECTURE.md)

## Commands

```bash
ariaflow add <url>
ariaflow preflight
ariaflow run
ariaflow serve
ariaflow status
ariaflow ucc
```

You can also run it as a module:

```bash
python -m aria_queue add <url>
```

## Goals

- Prefer finishing one download before starting the next.
- Allow operators to raise concurrency explicitly when they need it.
- Start with a conservative bandwidth cap derived from a short probe.
- Lower the cap when aria2 reports retries or errors.
- Keep post-download handling policy-driven and separate from the queue engine.
- Emit a structured UCC result for each run.

## Storage

Default files live under `~/.config/aria-queue/`:

- `queue.json`
- `state.json`
- `aria2.log`

## Post actions

The post-action layer is intentionally not fixed yet. The tool exposes hooks for:

- `move`
- `rename`
- `verify`
- `import`
- custom script execution

Define rules later in `config/post-actions.json`.

## UIC / UCC / TIC status

- UIC: minimal pre-flight gate resolution exists.
- UCC: structured result output exists for the main execution path.
- TIC: tests declare intent in docstring form and verify observable result shapes.

This is still a minimal compliance layer, not a full framework implementation.

## Homebrew

The intended macOS installation path is a Homebrew tap.

- `ariaflow` installs the headless engine
- `ariaflow-web` installs the local frontend
- both are meant to run on the same Mac

The web UI lives in the separate `ariaflow-web` project and talks to this
backend over the local `/api/*` HTTP surface.

`ariaflow` is API-only. It exposes a small landing page at `/` to explain the
boundary, but the dashboard routes are not hosted here.

`ariaflow` depends on `aria2` as the runtime engine. `ariaflow-web` depends on a
running `ariaflow` backend and connects to it through `ARIAFLOW_API_URL`.

The Homebrew tap formulas live in `bonomani/homebrew-ariaflow`:

- `Formula/ariaflow.rb`
- `Formula/ariaflow-web.rb`

Both source repos now update their matching Homebrew formulas automatically
after a stable GitHub release is published.

If an asset download location changes, update the tap formula for the new asset
instead of patching Homebrew globally.

## Release Tooling

The dedicated release checklist lives in [`RELEASE.md`](./RELEASE.md).

The repo ships a small publish helper:

```bash
python3 scripts/publish.py push
```

Preview the steps without changing files:

```bash
python3 scripts/publish.py plan
```

That script will:

- run the local test suite
- push `main` with a `pull --rebase` retry if needed
- optionally trigger an explicit `workflow_dispatch` release with `release --version X.Y.Z`
- optionally print the plan first with `plan`

Normal patch releases come from the GitHub Actions workflow on `main` pushes.
Use `release --version X.Y.Z` only when you need to force an explicit release.

After the push or explicit dispatch, the GitHub release workflow publishes the release and
updates `bonomani/homebrew-ariaflow/Formula/ariaflow.rb` directly.

The workflow also expects a repo secret named `ARIAFLOW_TAP_TOKEN` with write
access to `bonomani/homebrew-ariaflow` so the formula update can be pushed.
