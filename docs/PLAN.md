# Plan

### ⏸ [High] Final naming alignment — BLOCKED: awaiting frontend review

> **DO NOT IMPLEMENT** until the frontend agent has reviewed this plan
> and confirmed no breaking changes to `ariaflow-web`. The frontend
> agent should comment in `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md`
> or update this section with approval/objections.

**What:** Align all internal names with the `ariaflow-server` package rename.
Currently the Python module, env var, config dir, and API keys still use
the old `aria_queue` / `aria-queue` / `ariaflow` names.

**Why:** A user running `pipx install ariaflow-server` then sees
`~/.config/aria-queue/`, `ARIA_QUEUE_DIR`, and `"ariaflow"` in API
responses. Confusing for humans and AI agents alike.

---

#### 1. Config dir: `aria-queue` → `ariaflow-server`

**Current:** `~/.config/aria-queue/` (all platforms)
**Proposed:** `~/.config/ariaflow-server/` (Linux/WSL),
`~/Library/Application Support/ariaflow-server/` (macOS),
`%LOCALAPPDATA%/ariaflow-server/` (Windows)
**Migration:** On first start, if old dir exists and new doesn't, move it.
**Frontend impact:** None — frontend connects via HTTP, never reads config dir.
**Scope:** `storage.py:18-21`, migration helper, ~20 lines

---

#### 2. Env var: `ARIA_QUEUE_DIR` → `ARIAFLOW_DIR`

**Current:** `ARIA_QUEUE_DIR` overrides config dir
**Proposed:** `ARIAFLOW_DIR` (accept both, prefer new, warn on old)
**Frontend impact:** None — env var is backend-only.
**Scope:** `storage.py:20`, ~5 lines + deprecation warning

---

#### 3. API key: `"ariaflow"` → `"ariaflow-server"` in responses

**Current:** `GET /api/status` returns `{"ariaflow": {"version": ...}}`,
`GET /api/meta` returns `{"name": "ariaflow"}`,
`GET /api/lifecycle` returns `{"ariaflow": {...}}`
**Proposed:** Change to `"ariaflow-server"` in all three.
**⚠ Frontend impact:** BREAKING — `ariaflow-web` reads `status.ariaflow.version`,
`lifecycle.ariaflow`, etc. Frontend must update `app.js` to use
`status["ariaflow-server"]` or the API must serve both keys during transition.
**Transition option:** Return both `"ariaflow"` and `"ariaflow-server"` keys
for one release cycle, then drop `"ariaflow"`.
**Scope:** `webapp.py:287-292`, `routes/meta.py:29`, `routes/lifecycle.py`,
`install.py` (plan dict keys), `openapi_schemas.py`, both `openapi.yaml`.
~30 lines changed.

---

#### 4. Python module: `aria_queue` → `ariaflow_server`

**Current:** `src/aria_queue/` — every import uses `from aria_queue.xxx`
**Proposed:** `src/ariaflow_server/`
**Frontend impact:** None — frontend never imports Python modules.
**⚠ Test impact:** Every mock target (`patch("aria_queue.xxx.yyy")`) changes.
**Scope:** ~200 files, fully mechanical rename. High risk of merge conflicts
if other work is in progress. Best done in a quiet period.
**Approach:** `git mv src/aria_queue src/ariaflow_server`, then global
find-replace `aria_queue` → `ariaflow_server` in all `.py` files,
`pyproject.toml`, `CLAUDE.md`, and test mocks.

---

#### 5. Consolidate governance docs (optional, non-breaking)

**Current:** 7 files in `docs/governance/` (BGS, BISS, TIC, ASM, etc.)
with overlapping concepts. AI agents and new contributors have to
cross-reference all of them.
**Proposed:** Merge into a single `docs/GOVERNANCE.md` with sections.
**Frontend impact:** None.
**Scope:** ~1 file created, 7 removed

---

#### 6. Split `install.py` (optional, non-breaking)

**Current:** `install.py` handles version detection, Homebrew operations,
UCC envelope generation, platform dispatch, and status reporting (~340 lines).
**Proposed:** Extract `ucc.py` (envelope helpers) and keep `install.py`
as orchestration only.
**Frontend impact:** None.
**Scope:** 1 new file, 1 refactored

---

**Execution order (after frontend approval):**
- Phase 1 (non-breaking): Steps 1, 2, 5, 6 — can ship immediately
- Phase 2 (breaking API): Step 3 — needs frontend coordination, dual-key transition
- Phase 3 (big rename): Step 4 — do in a quiet period, single commit

**Frontend agent action required:**
Please review steps 1-4 and confirm:
- [ ] Step 1 (config dir): OK / objection
- [ ] Step 2 (env var): OK / objection
- [ ] Step 3 (API key): Preferred transition strategy (dual-key? hard cut?)
- [ ] Step 4 (module rename): OK / timing preference

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
