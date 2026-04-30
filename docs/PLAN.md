# Plan

## Open

### [P2] Sync `openapi.yaml` with live Fastify routes

**What:** `node scripts/check-openapi-drift.mjs` reports 18 paths registered live but missing from `openapi.yaml`, plus 2 method-set mismatches:

- Missing paths: `/api/_meta`, `/api/actions`, `/api/active`, `/api/aria2/{global_option,multicall,option}`, `/api/downloads`, `/api/downloads/{id}`, `/api/openapi`, `/api/preflight`, `/api/scheduler/{start,stop}`, `/api/sessions/{close,current,history,start}`, `/api/version`, plus the `*` fallback.
- Method-set drift: `/api/declaration` live `GET,POST,PUT` vs spec `GET,POST` (add `PUT`); `/api/declaration/preferences` live `PATCH,POST` vs spec `PATCH` (add `POST`).

**Where:** `openapi.yaml` (root). Handler signatures live in `packages/api/src/server.ts`.

**Why:** `openapi.yaml` is the public API contract the dashboard reads. Drift means the contract lies about what's available.

**Scope:** medium — each missing path needs a stub with request/response schema. Aim for parity with existing entries' style (tags, summary, 200 response). ~150–250 lines.

**Verify:** `node scripts/check-openapi-drift.mjs` exits 0.

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
□ pnpm test                     # all tests pass
```

For each plan item:
```
□ read the plan item
□ read the code to change
□ implement the change (smallest diff possible)
□ pnpm test                     # all tests pass
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
□ pnpm test                     # final pass
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
