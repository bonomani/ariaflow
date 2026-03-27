# Release

`ariaflow` is the source repo for the headless engine and the Homebrew-driven
release flow.

## Preferred Flow

Run the helper from a clean checkout on `main`:

```bash
python3 scripts/publish.py plan
python3 scripts/publish.py push
```

The helper will:

- validate that `pyproject.toml` and `src/aria_queue/__init__.py` agree
- refuse to reuse an existing tag
- run `py_compile` and `python3 -m unittest discover -s tests -v` unless `--no-tests` is used
- `push`: push `main` with a `pull --rebase` retry
- `release --version X.Y.Z`: trigger `workflow_dispatch` for an explicit stable version after the same rebase-safe sync

Useful flags:

- `plan`: print the release plan without changing files
- `release --version 0.1.2`: dispatch an explicit stable release on GitHub Actions
- `--no-tests`: skip local tests
- `plan --allow-dirty`: bypass the clean-tree check for preview only

## After Push

The GitHub workflow in `.github/workflows/release.yml` runs automatically on
`main` pushes and can also be triggered explicitly with `workflow_dispatch`. It will:

- run the test suite again on GitHub Actions
- build the source distribution
- create the GitHub release
- update `bonomani/homebrew-ariaflow/Formula/ariaflow.rb` directly

## Manual Flow

If you do not use the helper, keep the sequence the same:

1. Commit the code change on `main`.
2. Push `main`.
3. Let GitHub Actions create the release commit, stable tag, GitHub release, and Homebrew update.

If you need to force a specific stable version:

```bash
python3 scripts/publish.py release --version 0.1.2
```

## Verification

After release:

- verify the GitHub release is published as a normal release
- verify the Homebrew tap formula updated to the same version
- on macOS, check:

```bash
brew tap bonomani/ariaflow
brew upgrade ariaflow
ariaflow --version
```

## GitHub Secret

Set `ARIAFLOW_TAP_TOKEN` in this repo with write access to
`bonomani/homebrew-ariaflow`. The release workflow uses it to commit the
formula update.

## Tooling Note

The automated publish path only needs `git`, Python, `gh`, and the
`ARIAFLOW_TAP_TOKEN` GitHub secret.
