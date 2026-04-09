# Plan


### [Medium] G-8: Update BGS version refs

**What:** Check if BGS upstream (`bonomani/bgs`) has new SHAs. If so, update `bgs_version_ref` and all `member_version_refs` in BGS.md + bgs-decision.yaml, then re-run `check-bgs-compliance.py`
**Where:** `docs/governance/BGS.md`, `docs/governance/bgs-decision.yaml`
**Why:** Pinned refs `bgs@58c1467` may be outdated. Stale refs mean the claim references a version of BGS that may have evolved.
**Scope:** 2 files, ~10 lines. Requires read access to `../BGSPrivate/`
**Depends on:** Nothing

---

### [Medium] G-9: Add Windows/WSL setup to README

**What:** Add a "Platform setup" section to README covering:
- Windows: Bonjour requirement (iTunes or standalone SDK) for peer discovery
- WSL2: mirrored networking for LAN visibility, `dns-sd.exe` interop
- `ARIAFLOW_DIR` env var override
- Software dependencies table by OS
**Where:** `README.md`
**Why:** No documentation for Windows/WSL users. Bonjour silently disabled without guidance.
**Scope:** ~30 lines added to README
**Depends on:** Nothing

---

---

### [Low] G-4: Report Bonjour availability in /api/status

**What:** Add `"discovery": {"available": bool, "backend": str|null}` to the `/api/status` response
**Where:** `src/ariaflow_server/webapp.py:_status_payload()`, `src/ariaflow_server/openapi_schemas.py`
**Why:** Discovery silently disabled when Bonjour unavailable. Frontend and users have no way to know.
**Scope:** ~10 lines source + schema + test
**Depends on:** Nothing
**TIC:** Register in tic-oracle.md

---

### [Low] G-10: Add migration section to README

**What:** Document breaking changes for users upgrading from pre-0.1.163:
- Config dir auto-migrated (`~/.config/aria-queue/` → `~/.config/ariaflow-server/`)
- Env var: `ARIAFLOW_DIR` replaces `ARIA_QUEUE_DIR` (both accepted)
- API keys: `"ariaflow"` → `"ariaflow-server"` in responses (breaking)
- Bonjour: `_ariaflow-server._tcp` (breaking for peer discovery)
**Where:** `README.md`
**Why:** No migration guide for breaking API changes.
**Scope:** ~20 lines
**Depends on:** G-9 (combine in same README update)

---

### [Low] G-7: Renumber TIC oracle sequentially

**What:** Replace sub-IDs (`22a`, `232b`, `428a`) with sequential numbers. Update coverage summary total.
**Where:** `docs/governance/tic-oracle.md`
**Why:** Sub-IDs create ambiguity and drift between registered count and total.
**Scope:** Mechanical renumber, ~50 lines changed
**Depends on:** Do last — any other TIC changes should land first

---

### [Low] G-11: Test on Python 3.14 in CI

**What:** Add Python 3.14 to the test matrix in `.github/workflows/release.yml` or a separate test workflow
**Where:** `.github/workflows/release.yml` or new `test.yml`
**Why:** Homebrew installs Python 3.14 on macOS but CI only tests 3.12.
**Scope:** ~5 lines in workflow YAML
**Depends on:** Nothing

---


---

## How to use this file

This is the **single plan file** for the project. Do not create separate plan files.

### Rules

0. **Task 0: clean git before starting.** Before executing any plan item, verify `git status` is clean (no uncommitted changes, no untracked files except `.claude/`). Show the output as evidence. If not clean, commit or stash first. Never start work on a dirty tree.
1. **One plan file.** All planned work goes here. No `BUGFIX_PLAN.md`, `REFACTOR_PLAN.md`, etc.
2. **Done → remove.** When an item is completed, delete it from this file. Git history has the record.
3. **Declined → keep briefly.** If an item was evaluated and rejected, keep a one-liner with the reason. This prevents re-proposing the same idea.
4. **Empty → keep the file.** Even with no open items, keep this file with the instructions.
5. **Prioritize.** Items are ordered by priority. Top = do first.
6. **Be concrete.** Each item has: what to change, where in the code, why, and estimated scope.
7. **Checkpoint after each item.** Run tests, commit, update docs.
8. **No stale plans.** If a plan item has been open for more than 2 sessions without progress, re-evaluate it — either do it or decline it.

### Execution workflow

Before starting:
```
□ git status                    # must be clean
□ git pull --rebase origin main # start from latest
□ python -m pytest tests/ -x -q # all tests pass
```

For each plan item:
```
□ read the plan item
□ read the code to change
□ implement the change (smallest diff possible)
□ python -m pytest tests/ -x -q # all tests pass
□ update docs if affected
□ git add <specific files>      # no git add -A
□ git commit                    # descriptive message
□ remove the item from PLAN.md
□ git add docs/PLAN.md
□ git commit "Update plan"
□ git push origin main          # if rejected: pull --rebase, re-test, push
```

After all items done:
```
□ python -m pytest tests/ -x -q # final pass
□ python scripts/gen_rpc_docs.py # regenerate if code changed
□ python scripts/gen_all_variables.py --check # naming compliance
□ verify PLAN.md says "No open items"
□ git push origin main
□ rm -rf .claude/worktrees/     # clean temp working folders
□ git status                    # confirm clean tree
```

### What NOT to do

- Don't start coding without checking `git status` first
- Don't batch multiple plan items into one commit
- Don't use `git add -A` (risk of committing secrets or generated files)
- Don't skip tests between items
- Don't leave uncommitted changes when stopping work
- Don't create plan files other than this one
- Don't `git checkout` or `git reset --hard` without understanding what will be lost (uncommitted work is gone forever)
- Don't modify code you haven't read first

### Item template

```
### [Priority] Short title

**What:** Description of the change
**Where:** File(s) and function(s) affected
**Why:** Problem it solves or value it adds
**Scope:** Estimated lines changed / files touched
**Depends on:** Other items that must be done first (if any)
```

---

## Declined

_Items evaluated and rejected. Kept to prevent re-proposing._

- **Remove `stopped` status** — `stopped` (system decided) vs `cancelled` (user decided) is a useful distinction. Merging them loses information.
- **Per-torrent Bonjour advertisement** — Replaced by API-based discovery (`GET /api/torrents`). Single service advertisement is simpler and Apple-compliant.
- **Scheduler start/stop API** — Scheduler now auto-starts with `ariaflow serve`. Users can only pause/resume. Simpler state model.
