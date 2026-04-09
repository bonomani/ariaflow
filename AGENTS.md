# Repository Workflow

Source repo for `ariaflow-server`. Documentation lives in [`docs/`](./docs/).

## Working Rules

- WSL checkout is the source repo
- Make edits and commits in WSL
- Use Git to sync companion repos/mirrors
- Keep release state aligned across source and Homebrew tap

## Release

```bash
python3 scripts/publish.py plan    # preview
python3 scripts/publish.py push    # push main + auto-release
```

For explicit stable version: `python3 scripts/publish.py release --version X.Y.Z`

See [`docs/RELEASE.md`](./docs/RELEASE.md) for full details.

## Verification

1. Check GitHub release is published (not draft/prerelease)
2. Check Homebrew formula version in tap repo
3. On macOS: `brew tap bonomani/ariaflow-server && brew upgrade ariaflow-server && ariaflow --version`

## Homebrew Notes

- Release workflow writes tap formula from `scripts/homebrew_formula.py` to `bonomani/homebrew-ariaflow-server`
- Generated formula tracks `main` for `--HEAD`
- Don't leave the tap pointing at an older tag after a new release

If this file conflicts with a direct user instruction, follow the user instruction.
