# Release Process

## Quick Release

```bash
git tag v0.1.X && git push origin v0.1.X
```

That's it — the rest is GitHub Actions. Pushing to `main` also tags
automatically via the existing release pipeline (next-patch).

## What GitHub Actions Does

On every `v*` tag push:

| Workflow | Effect |
|---|---|
| `release-npm.yml` | Publishes `@ariaflow/{core,api,cli}` to npm |
| `release-ts-formula.yml` | Renders the Homebrew formula and attaches `ariaflow-server-ts.rb` to the GitHub release |
| `release-ts-tap.yml` | Mirrors the formula into `bonomani/homebrew-ariaflow-server-ts` |
| `node.yml` | Typecheck / lint / test / build (CI on every push) |

## Explicit Version Release

```bash
gh workflow run release-npm.yml -f tag=v0.1.X
gh workflow run release-ts-formula.yml -f tag=v0.1.X
gh workflow run release-ts-tap.yml -f tag=v0.1.X
```

Useful for backfilling missing assets without re-tagging.

## Verification

```bash
# npm
npm view @ariaflow/cli version

# Homebrew
brew tap bonomani/ariaflow-server-ts
brew install ariaflow-server
ariaflow --version
```

## Prerequisites (repo secrets)

- `NPM_TOKEN` — automation token with publish access to the `@ariaflow` scope
- `TAP_PUSH_TOKEN` — fine-scoped PAT or GitHub App token with `contents: write` on `bonomani/homebrew-ariaflow-server-ts`

Missing secrets cause the affected workflow to skip cleanly (logged,
not errored) so the rest of the pipeline still succeeds.
