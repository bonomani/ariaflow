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
  - `python3 scripts/publish.py push`
- Use `plan` first if you want to preview the exact release plan.
- If you need an explicit stable version, use:
  - `python3 scripts/publish.py release --version X.Y.Z`
- If you need to do it manually, commit on `main`, push `main`, and let the
  release workflow publish the release.
- Verify the release is `isDraft: false` and `isPrerelease: false`.
- The release workflow only publishes stable tags and updates `bonomani/homebrew-ariaflow/Formula/ariaflow.rb` directly after publishing the release.

Homebrew notes:

- The release workflow writes the tap formula from `scripts/homebrew_formula.py`.
- The generated formula tracks `main` for `--HEAD`.
- Do not leave the tap pointing at an older stable tag after a new release is published.

Verification:

- Check the source release on GitHub.
- Check the Homebrew formula version in the tap repo.
- On macOS, verify with:
  - `brew tap bonomani/ariaflow`
  - `brew upgrade ariaflow`
  - `ariaflow --version`

If this file conflicts with a direct user instruction, follow the user instruction.
