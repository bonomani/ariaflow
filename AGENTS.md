# Repository Workflow

This repository is the source repo for `ariaflow`.

Working rules:

- Treat the WSL checkout as the source repo.
- Make edits and commits in WSL.
- Use Git to sync any companion repo or mirror.
- Keep release state aligned across the source repo and the Homebrew tap.

Release workflow:

- Make the code change in `ariaflow`.
- Run the local test suite before tagging.
- Prefer the helper script:
  - `python3 scripts/release.py --next-alpha --push`
- Use `--dry-run` first if you want to preview the exact release plan.
- If you need to do it manually, bump the package version in `pyproject.toml`
  and `src/aria_queue/__init__.py`, commit on `master`, create and push the tag,
  and let the release workflow publish the prerelease.
- Verify the release is `isDraft: false` and `isPrerelease: true` for alpha releases.
- The release workflow automatically dispatches a `sync-formula` event to `bonomani/homebrew-ariaflow` via `repository_dispatch` after publishing the release. The tap formula is updated automatically.

Homebrew notes:

- The tap repo (`bonomani/homebrew-ariaflow`) syncs automatically on each release via the dispatch in `release.yml`.
- The sync picks the latest non-draft release sorted by `created_at` descending.
- Do not leave the tap pointing at an older alpha tag after a new prerelease is published.

Verification:

- Check the source release on GitHub.
- Check the Homebrew formula version in the tap repo.
- On macOS, verify with:
  - `brew tap bonomani/ariaflow`
  - `brew upgrade ariaflow`
  - `ariaflow --version`

If this file conflicts with a direct user instruction, follow the user instruction.
