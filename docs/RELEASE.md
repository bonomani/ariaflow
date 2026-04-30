# Release Process

## Automatic Releases (default)

Every successful `node` CI run on `main` triggers `auto-tag.yml`,
which bumps the latest `vX.Y.Z` patch and pushes the new tag. The
tag push fans out to `release-npm`, `release-tap`, and
`release-formula`.

**Required setup:** the `RELEASE_PAT` repo secret (a Personal Access
Token with `contents: write` scope on this repo) must be set. Tags
pushed by the default `GITHUB_TOKEN` from inside a workflow do **not**
trigger downstream workflows (a GitHub security feature), so the PAT
is what makes the cascade work. If `RELEASE_PAT` is missing, the
auto-tag job no-ops with a warning in the workflow log.

## Manual Release (override)

If you want to control the version explicitly (e.g. minor/major bump,
or to back-fill a release):

```bash
git tag v0.2.0 && git push origin v0.2.0
```

A real push from a developer machine triggers the release workflows
the same way. The auto-tagger only increments patch from the latest
`vX.Y.Z` — pushing a manual minor/major bump shifts the baseline,
and the next auto-bump computes from there.

## What GitHub Actions Does

On every `v*` tag push:

| Workflow | Effect |
|---|---|
| `release-npm.yml` | Publishes `@ariaflow/{core,api,cli}` to npm |
| `release-formula.yml` | Renders the Homebrew formula and attaches `ariaflow-server.rb` to the GitHub release |
| `release-tap.yml` | Mirrors the formula into `bonomani/homebrew-ariaflow-server` |
| `node.yml` | Typecheck / lint / test / build (CI on every push) |

## Explicit Version Release

```bash
gh workflow run release-npm.yml -f tag=v0.1.X
gh workflow run release-formula.yml -f tag=v0.1.X
gh workflow run release-tap.yml -f tag=v0.1.X
```

Useful for backfilling missing assets without re-tagging.

## Verification

```bash
# npm
npm view @ariaflow/cli version

# Homebrew
brew tap bonomani/ariaflow-server
brew install ariaflow-server
ariaflow --version
```

## Prerequisites (repo secrets)

- `RELEASE_PAT` — PAT with `contents: write` on this repo. Required for `auto-tag.yml` to push tags that trigger the downstream release workflows.
- `NPM_TOKEN` — automation token with publish access to the `@ariaflow` scope
- `TAP_PUSH_TOKEN` — fine-scoped PAT or GitHub App token with `contents: write` on `bonomani/homebrew-ariaflow-server`

Missing secrets cause the affected workflow to skip cleanly (logged,
not errored) so the rest of the pipeline still succeeds.
