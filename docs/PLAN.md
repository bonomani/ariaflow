# Plan

## Open items

Source: `scripts/check_tic_coverage.py` output (2026-04-08).
Goal: bring TIC oracle coverage to 100%, then flip the checker to enforcing so any new uncovered test fails `make verify` immediately.

### [P2] Register the 78 unregistered tests in tic-oracle.md

**What:** 78 tests run but have no oracle entry. The oracle promises every test has explicit `Intent / Oracle / Trace Target` columns; today 78 of them have nothing.

**Where:** `docs/governance/tic-oracle.md` — append rows for every missing test. Group by source file / test class so the table stays scannable. The 78 missing names live in `python scripts/check_tic_coverage.py` output.

**Why:** Closes the last gap before the oracle can be treated as authoritative. Required before P3.

**Scope:** Big — 78 hand-curated rows. Naive registration is cheap but low-value; the rows need real `Intent` and `Trace Target` content to be useful. Two execution strategies:
- (a) **Bulk shallow registration** — one commit, one row per test, generic intent like "runs without error". Closes the count gap but adds little semantic value. ~30 minutes.
- (b) **Per-class deep registration** — group the 78 by test class, write meaningful Intent/Oracle/Trace for each. Multiple commits, one per class. Higher value, ~2-3 hours.

**Decision needed before starting:** pick (a) or (b), or a hybrid (deep for high-value classes, shallow for the rest).

**Depends on:** P1 — start from a clean stale list so each commit's diff is interpretable.

### [P3] Flip `check_tic_coverage.py` to enforcing

**What:** Once P1 and P2 land, change `ALWAYS_PASS = True` to `ALWAYS_PASS = False` in `scripts/check_tic_coverage.py`. The script then exits 1 on any drift, and `make verify` fails until the oracle is updated.

**Where:** `scripts/check_tic_coverage.py:36`.

**Why:** The whole point of the checker is to catch drift the moment it happens. Until P3, drift is reported but accumulates silently.

**Scope:** 1 line.

**Verify:** `make verify` still passes (preconditions: P1 and P2 done — `0 missing, 0 stale`).

**Depends on:** P1 + P2.

---

Deferred (informational only):
- `check_declaration_drift.py` reports 23 prefs in code missing from the user declaration file. Tracked separately by the existing `|| true` warn-only setup; out of scope for the TIC oracle work.

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
- **Per-torrent Bonjour advertisement** — Replaced by API-based discovery (`GET /api/torrents`). Single `_ariaflow._tcp` service is simpler and Apple-compliant.
- **Scheduler start/stop API** — Scheduler now auto-starts with `ariaflow serve`. Users can only pause/resume. Simpler state model.
