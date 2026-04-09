# Coding Rules — Lessons Learned

Rules derived from real incidents during development. Each rule exists because we made the mistake.

## 1. Git Safety

### R1: NEVER use `git checkout --` on uncommitted work
**Incident:** `git checkout -- src/aria_queue/core.py` reverted all Phase A, B, B+ changes — hours of work lost permanently.
**Rule:** Before any destructive git command (`checkout --`, `reset --hard`, `clean -f`), always `git stash` first. Better: commit at every checkpoint.
**Enforcement:** Documented in `docs/PLAN.md` Rule 0.

### R2: Commit at every checkpoint, not at the end
**Incident:** All changes were uncommitted when the git checkout happened. If we had committed after each phase, only the current phase would have been lost.
**Rule:** After each logical change that passes tests → commit immediately. Never batch multiple changes into one big commit.

### R3: Never commit generated files
**Incident:** `src/ariaflow_server.egg-info/` was accidentally committed.
**Rule:** Run `git diff --cached --stat` before commit. Add generated directories to `.gitignore` proactively. Current gitignore: `.claude/`, `src/ariaflow_server.egg-info/`, `docs/ALL_VARIABLES.md`.

## 2. Renaming

### R4: Rename longest names first to avoid substring corruption
**Incident:** Renaming `pause_gid(` → `aria2_pause(` also hit `unpause_gid(` → `unaria2_pause(`. Similarly `pause_all(` → `aria2_pause_all(` corrupted `force_pause_all(` → `force_aria2_pause_all(`.
**Rule:** When bulk-renaming with sed/replace_all, always process longest names first. Or use word-boundary regex (`\b`). Verify with grep after.

### R5: After any rename, grep ALL files — not just source
**Incident:** After renaming `active_gids` → `aria2_tell_active` in source, tests still patched `aria_queue.core.active_gids` and failed.
**Rule:** After renaming a public function:
1. `grep -rn 'old_name' src/ tests/ docs/ scripts/` — catch all references
2. Update source, tests, docs, scripts, openapi.yaml
3. Run tests before committing

### R6: After moving functions between modules, update test mock targets
**Incident:** After splitting `webapp.py` → `routes/`, tests patching `aria_queue.webapp.homebrew_install_ariaflow` failed because the function was now imported in `routes/lifecycle.py`. CI release failed.
**Rule:** When moving a function from module A to module B, every `patch("module_A.function")` in tests must become `patch("module_B.function")`. Search: `grep -rn 'module_A.function' tests/`.

## 3. Documentation

### R7: Auto-generate everything that can drift
**Incident:** OpenAPI spec had 18 endpoints when the code had 44. Manual YAML maintenance failed silently.
**Rule:** If a doc reflects code structure, auto-generate it:
- `scripts/gen_openapi.py` → `openapi.yaml`
- `scripts/gen_rpc_docs.py` → `docs/ARIA2_RPC_WRAPPERS.md`
- `scripts/gen_all_variables.py` → `docs/ALL_VARIABLES.md`
- Run all with `make docs`. Never edit generated files by hand.

### R8: One plan file, remove done items
**Incident:** Multiple plan files (BUGFIX_PLAN.md, REFACTOR_PLAN.md, etc.) with overlapping items, stale decisions contradicting actual code.
**Rule:** One plan: `docs/PLAN.md`. Done items → delete (git has history). Declined items → keep one-liner with reason.

### R9: After endpoint renames, grep all docs
**Incident:** After renaming `/api/run` → `/api/scheduler/start`, 19 stale references remained across 5 doc files.
**Rule:** After renaming any API endpoint: `grep -rn '/api/old_name' docs/ README.md CONTRIBUTING.md`. Fix all references before committing.

## 4. Code Quality

### R10: Variable shadowing — never reuse a variable name with different units
**Incident:** `up_cap` was first set to mbps (float), then overwritten with bytes/sec (int). The return dict used the variable after overwrite, returning bytes where mbps was expected.
**Rule:** Use distinct names: `up_cap_mbps` vs `up_cap_bytes`. Never reassign a variable to a value with different units/types.

### R11: Test the sad path of subprocess.Popen
**Incident:** `aria2_ensure_daemon()` called `subprocess.Popen("aria2c", ...)` but didn't catch `FileNotFoundError` when aria2c wasn't installed. Gave confusing Python traceback.
**Rule:** Every `subprocess.Popen()` or `subprocess.run()` must handle `FileNotFoundError` (binary not found) and `PermissionError` (not executable).

### R12: Status cache must be thread-safe
**Incident:** `STATUS_CACHE` dict was read/written by multiple HTTP handler threads without a lock. Race condition.
**Rule:** Any shared mutable state accessed by HTTP handler threads must use `threading.Lock()`.

### R13: `str(obj)` on non-string types is a bug smell
**Incident:** `str(gids)` where `gids` was a list returned `"['gid1']"` instead of `"gid1"`. Same for `gid = str(item.get("gid") or "")` mixing None and empty string.
**Rule:** Never use `str()` as a fallback converter. Check the actual type: `if isinstance(gids, list) and gids: return gids[0]`.

## 5. Refactoring

### R14: Worktree agents must use the current commit
**Incident:** Agent created modules in a worktree based on an older commit (before our changes). The modules had outdated function bodies. Couldn't merge.
**Rule:** When using isolation worktrees for refactoring, ensure the worktree is based on the latest committed code. Commit all changes first.

### R15: Keep re-export hub when splitting modules
**Incident:** After splitting `core.py` into 7 modules, all tests patching `aria_queue.core.X` still worked because `core.py` became a re-export hub.
**Rule:** When splitting a module, keep the original filename as a re-export hub using `from .new_module import *`. This ensures all existing `import` and `patch()` statements continue working.

### R16: Split helpers — single-use helpers go with their handler
**Incident:** Plan put all helpers in `helpers.py`. Analysis showed most helpers (11/12) were used by only 1 handler. Putting them all in helpers.py was wrong.
**Rule:** Only truly shared helpers (used by 3+ callers) go in a shared file. Single-use helpers move with their handler function.

## 6. API Design

### R17: Keep a single root openapi.yaml synced
**Incident:** Root `openapi.yaml` and `src/aria_queue/openapi.yaml` diverged. Tests read from root, code served from src.
**Rule:** `gen_openapi.py` writes to both files. Never edit either manually. `make docs` keeps them in sync.

### R18: Use consistent endpoint naming from the start
**Incident:** API grew organically — `/api/add`, `/api/run`, `/api/pause` mixed with `/api/scheduler/start`, `/api/aria2/change_global_option`. Required a full rename pass.
**Rule:** Every endpoint follows `POST /api/{resource}/{action}` or `GET /api/{resource}`. Agree on the pattern before adding new endpoints.

## Quick Checklist (before every commit)

```
□ git status                    — no surprise files
□ pytest -x                     — all tests pass
□ gen_all_variables.py --check  — naming compliance
□ grep for old names            — if anything was renamed
□ make docs                     — if endpoints/functions changed
□ git diff --cached --stat      — review what's staged
```
