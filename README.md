# aria-queue

Cross-platform queue driver for `aria2c` with:

- simple URL enqueueing
- sequential execution, one download at a time
- pre-run bandwidth probing
- runtime bandwidth adaptation through aria2 RPC
- pluggable post-download actions
- UIC pre-flight checks
- UCC structured execution output
- TIC-style tests
- local web UI

Targets:

- Linux
- WSL
- macOS

## Commands

```bash
ariaflow add <url>
ariaflow preflight
ariaflow run
ariaflow status
ariaflow ucc
ariaflow serve
```

You can also run it as a module:

```bash
python -m aria_queue add <url>
```

## Goals

- Prefer finishing one download before starting the next.
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

## Web UI

The web mode is intentionally local-only:

- binds to `127.0.0.1` by default
- serves one page
- exposes JSON endpoints under `/api/*`
- keeps `aria2` as the download engine

Run it with:

```bash
ariaflow serve
```

## Homebrew

The intended macOS installation path is a Homebrew tap. The formula's `url`
points at a versioned upstream archive. When you publish a new version, update:

- the formula `url`
- the formula `sha256`
- the formula `version`

If the download location changes, you do not patch Homebrew globally; you update
the tap formula for the new asset.
