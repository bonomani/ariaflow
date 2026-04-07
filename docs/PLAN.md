# Plan

## Open items

Source: `docs/governance/BGS-GAPS.md` (analysis of BGSPrivate @ 58c1467).
Goal: make `check-bgs-compliance.py` pass against ariaflow.

### [P1] Repin members for BGSPrivate monorepo layout (G1)

**What:** Replace per-member SHAs with a single BGSPrivate ref. BGSPrivate is one git repo; `ucc/`, `uic/`, `asm/`, `tic/` are subfolders without `.git`, so `ucc@370c1f7` etc. cannot resolve.
**Where:**
- `docs/governance/bgs-decision.yaml:21-25` — set every entry to `<name>@58c1467` (the BGSPrivate HEAD).
- `docs/governance/BGS.md:31-35` — same.
- `scripts/check_bgs_drift.py:19-25` — point all five members at `_PROJECT.parent / "BGSPrivate"`.
**Why:** Without this, the upstream validator FAILs 4× on member refs and the local drift checker drifts from upstream truth.
**Scope:** ~15 lines, 3 files.
**Decision needed first:** confirm option (A) "pin everything to bgs@<sha>" before editing — see G1 in BGS-GAPS.md.
**Depends on:** none, but do after the path fixes so each commit is independently green.

### [P2] Schema-align external_controls casing + add biss ref (G5 + G6)

**What:** Lowercase `IAM_and_authorization` → `iam_and_authorization` in both files; add `biss: bgs@58c1467` to `member_version_refs` since `BISS` is in `members_used`.
**Where:**
- `docs/governance/bgs-decision.yaml:28`
- `docs/governance/BGS.md:24`
- `docs/governance/bgs-decision.yaml:21` and `BGS.md:31` (add biss line).
**Why:** Validator passes today via key normalization, but the JSON schema declares the canonical key as lowercase — any stricter runner fails. Adding `biss` matches the declared members list.
**Scope:** 4 lines, 2 files.

### [P2] Wire upstream validator into make check-drift (G7)

**What:** Have `scripts/check_bgs_drift.py` shell out to `../BGSPrivate/bgs/tools/check-bgs-compliance.py docs/governance/BGS.md --member-repos-root ../BGSPrivate` and propagate its exit code. Surface stdout on failure.
**Where:** `scripts/check_bgs_drift.py` (add a step at the end of `main()`); no Makefile change needed since it already calls this script.
**Why:** Local `make check-drift` currently reports `BGS clean` while upstream reports 10 FAILs. The two checks must agree.
**Scope:** ~20 lines, 1 file.
**Depends on:** P1 items above (otherwise the new step fails immediately).

### [P3] Refresh last_reviewed (G9)

**What:** Bump `last_reviewed: 2026-04-05` → `2026-04-07` in `BGS.md`.
**Where:** `docs/governance/BGS.md:12`.
**Why:** Reflect that the entry was just re-validated against the new suite.
**Scope:** 1 line.
**Depends on:** all P1/P2 items merged (only bump after the file is actually clean).

---

Deferred (informational only, no action this round):
- **G4** — document the single-SHA pinning convention once G1 lands.
- **G8** — Grade-2 fields (`profiles[]`, `policies[]`) — adopt only if we ship a typed profile.

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
