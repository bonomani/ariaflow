# Plan

## Open items

### [P3] BG-11: Residual under-specified fields after BG-10

**What:** Frontend filed BG-11 in `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md` after the BG-10 sweep. Their `tests/test_openapi_alignment.py` still surfaces 14 field-level gaps across 5 endpoints — mostly fields the BG-10 sweep missed because they live in shapes BG-10 didn't touch.

**Affected endpoints (per the frontend file):**
| Endpoint | Missing in openapi.yaml |
|---|---|
| `GET /api/status` | `created_at`, `enabled`, `output`, `percent`, `pid`, `reachable` |
| `GET /api/declaration` | `policy`, `ucc` (top-level buckets) |
| `GET /api/sessions` | `ended_at` |
| `GET /api/peers` | `ip` |
| `GET /api/downloads/archive` | `created_at`, `ended_at`, `next_cursor`, `output` |

**Where:** `src/aria_queue/openapi_schemas.py` for each endpoint. Some fields require checking the actual code path that builds them (e.g. `/api/peers ip` — the `_resolve_dns_sd` builder uses `host`, not `ip`; the frontend may be expecting a key that doesn't exist).

**Why:** Closes the last drift between the OpenAPI spec and the runtime shape. Once 0, the frontend can tighten `test_openapi_alignment.py` from `warnings.warn` to a hard assertion.

**Scope:** Smaller than BG-10 — each endpoint is 1-6 fields. Verify each missing field actually exists in the code path before adding it (some may be frontend-side aspirations rather than real omissions).

**Verify:** Same pattern as BG-10 — add a live-shape pinning test for each fixed endpoint, then `make verify` clean.

### [P3] Pre-existing lint and format debt blocking a strict `make ci`

**What:** `make lint` reports **27 ruff errors** (mostly unused imports — e.g. `tests/test_unit.py:723` imports `allowed_actions` "just to verify import works"). `ruff format --check` reports **35 files** that would be reformatted. Both predate this session.

**Why:** A `make ci` target that runs `verify + lint + format --check` was proposed but skipped because both pre-existing failures would make it red on first invocation. Once cleared, `make ci` becomes a 1-line addition.

**Where:**
- `make lint` output enumerates the 27 errors. Most are `F401` unused imports — `ruff check --fix src/ tests/` will auto-resolve 24 of them. The remaining 3 need hand inspection.
- `ruff format src/ tests/` (without `--check`) will rewrite the 35 files in place. Verify the resulting diff doesn't introduce semantic changes (it shouldn't — ruff format is whitespace/style only).

**Scope:**
- Lint pass: ~5 min for the auto-fixable 24, plus inspection for the 3 holdouts.
- Format pass: 1 command, 35-file diff. Single commit.
- `make ci` addition: 4 lines.

**Decision needed before starting:** confirm the bulk format diff is acceptable as a single commit (35 files touched, whitespace-only). If yes, do format → lint → add `make ci` as three commits in sequence.

---

Deferred (informational only):
- `check_declaration_drift.py` reports 23 prefs missing from the *user's local* `~/.config/aria-queue/declaration.json`. Not a repo issue — per-machine state. The existing `|| true` in the Makefile is correct.

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
