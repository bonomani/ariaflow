# Plan

### [B1] Add 6 managed option functions — no API change

**What:** Add dedicated aria2_set_* functions for upload limits, seed ratio/time. Rename existing ones for consistency. All delegate to aria2_change_global_option / aria2_change_option.
**Where:** `src/aria_queue/aria2_rpc.py`
**Why:** Upload limit probed but never applied. Naming inconsistent with aria2 option keys.
**Scope:** ~30 lines added. Rename 2 existing, add 4 new.

Functions (aria2_set_ + exact aria2 option key, hyphens → underscores):
- `aria2_set_bandwidth` → `aria2_set_max_overall_download_limit` (rename)
- `aria2_set_download_bandwidth` → `aria2_set_max_download_limit` (rename)
- `aria2_set_max_overall_upload_limit` (new)
- `aria2_set_max_upload_limit` (new)
- `aria2_set_seed_ratio` (new)
- `aria2_set_seed_time` (new)

### [B2] Apply upload cap after bandwidth probe — no API change

**What:** After probe, send `max-overall-upload-limit` to aria2 alongside download limit.
**Where:** `src/aria_queue/bandwidth.py` — `_apply_bandwidth_probe()`
**Why:** Upload cap is probed and calculated (`up_cap_mbps`) but never sent to aria2.
**Scope:** ~5 lines

### [B3] Three-tier option safety — no API change

**What:** Split `_SAFE_ARIA2_OPTIONS` into managed + safe + unsafe tiers. `POST /api/aria2/options` blocks managed options (must use dedicated function) and blocks unsafe options unless declaration preference allows.
**Where:** `src/aria_queue/aria2_rpc.py` (option sets), `src/aria_queue/webapp.py` (endpoint handler)
**Why:** Managed options have dedicated safe functions. Generic endpoint shouldn't bypass them.
**Scope:** ~20 lines. No new endpoints, same `POST /api/aria2/options` behavior.

Tiers:
- **Managed** (blocked from generic API): max-overall-download-limit, max-overall-upload-limit, max-download-limit, max-upload-limit, seed-ratio, seed-time
- **Safe** (allowed via generic API): max-concurrent-downloads, max-connection-per-server, split, min-split-size, timeout, connect-timeout
- **Unsafe** (allowed only with `aria2_unsafe_options: true` preference): everything else

### [B4] Add declaration preference for unsafe mode — no API change

**What:** Add `aria2_unsafe_options` preference (default false) to DEFAULT_DECLARATION.
**Where:** `src/aria_queue/contracts.py`
**Scope:** 5 lines

### [B5] Update callers — no API change

**What:** Replace `aria2_set_bandwidth` → `aria2_set_global_download_limit` in bandwidth.py, scheduler.py. Add `aria2_set_global_upload_limit` call alongside.
**Where:** `src/aria_queue/bandwidth.py`, `src/aria_queue/scheduler.py`
**Depends on:** B1, B2

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
