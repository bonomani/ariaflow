# ariaflow

Headless queue driver for `aria2c` with:

- simple URL enqueueing
- sequential execution, one download at a time
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

## Commands

```bash
ariaflow add <url>
ariaflow preflight
ariaflow run
ariaflow status
ariaflow ucc
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

## Homebrew

The intended macOS installation path is a Homebrew tap. The formula's `url`
points at a versioned upstream archive. The default formula covers the
`ariaflow` headless engine and expects `aria2` to be present as the runtime
engine.
When you publish a new version, update:

- the formula `url`
- the formula `sha256`
- the formula `version`

If the download location changes, you do not patch Homebrew globally; you update
the tap formula for the new asset.

## Release Tooling

The repo ships a small release helper:

```bash
python3 scripts/release.py --next-alpha --push
```

Preview the steps without changing files:

```bash
python3 scripts/release.py --next-alpha --dry-run
```

That script will:

- run the local test suite
- bump `pyproject.toml` and `src/aria_queue/__init__.py`
- commit the version bump
- create and push the `v0.1.1-alpha.N` tag
- optionally print the plan first with `--dry-run`

After the tag push, the GitHub release workflow publishes the prerelease and
dispatches the Homebrew tap sync.

The flow still expects a recent `gh` (GitHub CLI). The Ubuntu `jammy` archive
ships an older `gh` that is not suitable for the prerelease flow used here.

If you are on Ubuntu and need a newer `gh`, install it from GitHub's official
apt repository:

```bash
type -p curl >/dev/null || sudo apt install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh
```

Verify with:

```bash
gh --version
```

If you prefer to do the steps manually, the release helper is just a thin
wrapper around the same version bump, commit, tag, and push sequence.
