# Plan

### [Medium] Cross-platform support + PyPI publish

**Goal:** ariaflow installable and working on all platforms:

| Platform | Install ariaflow | Install aria2 | Service auto-start |
|----------|-----------------|---------------|-------------------|
| All | `pipx install ariaflow` (PyPI) | User's job | — |
| macOS | `brew install ariaflow` (existing) | Handled by brew | launchd (existing) |
| Windows | `pipx install ariaflow` | `winget install aria2` | Task Scheduler |
| Linux | `pipx install ariaflow` | `apt/dnf install aria2` | systemd user unit |

**Current blockers:** `import fcntl` crashes on Windows. `install.py`
hardcodes Homebrew/launchd. Not published to PyPI.

---

#### Step 1: Cross-platform file locking — `portalocker`

**Where:** `src/aria_queue/storage.py:9,65,79`, `pyproject.toml:10`
**What:** Replace `import fcntl` + `fcntl.flock()` with `portalocker`:
```python
import portalocker
# lock:
portalocker.lock(handle, portalocker.LOCK_EX)
# unlock:
portalocker.unlock(handle)
```
Add `portalocker` to `dependencies` in `pyproject.toml`.
**Why:** `portalocker` handles fcntl (Unix) / msvcrt (Windows) / edge
cases (timeouts, reentrant locks) in a battle-tested 300-line lib.
Zero transitive dependencies. 40M+ downloads/month. BSD license.
**Scope:** ~10 lines changed in `storage.py`, 1 line in `pyproject.toml`

---

#### Step 2: Platform detection helpers

**Where:** `src/aria_queue/platform/launchd.py:68` (move `is_macos` out)
**What:** Create `src/aria_queue/platform/detect.py`:
```python
import sys
def is_macos() -> bool: return sys.platform == "darwin"
def is_windows() -> bool: return sys.platform == "win32"
def is_linux() -> bool: return sys.platform.startswith("linux")
```
Update all imports of `is_macos` (6 call sites: `api.py`, `install.py`,
`webapp.py`, `routes/lifecycle.py`, `platform/launchd.py`) to import from
`platform.detect`.
**Scope:** 1 new file (~10 lines), ~6 import changes

---

#### Step 3: Guard `platform/launchd.py` imports

**Where:** `src/aria_queue/install.py:9-14`, `src/aria_queue/api.py:46-48`
**What:** These do `from .platform.launchd import ...` at module level.
On Windows, `os.getuid()` in `launchd.py` crashes even if the functions
aren't called. Use lazy imports guarded by `is_macos()`.
**Scope:** ~10 lines changed

---

#### Step 4: `platform/windows.py` — Task Scheduler integration

**Where:** New file `src/aria_queue/platform/windows.py`
**What:** Mirror `platform/launchd.py` using `schtasks.exe` (built-in):
- `task_scheduler_aria2_status()` — query task state
- `install_aria2_task()` — register aria2 as on-logon task:
  `schtasks /create /tn "ariaflow-aria2" /tr "aria2c --enable-rpc ..." /sc onlogon /f`
- `uninstall_aria2_task()` — `schtasks /delete /tn "ariaflow-aria2" /f`
- Session dir: `%LOCALAPPDATA%\ariaflow\.aria2\`
- Download dir: `Path.home() / "Downloads"`
**Scope:** ~120 lines, 1 new file

---

#### Step 5: `platform/linux.py` — systemd user unit integration

**Where:** New file `src/aria_queue/platform/linux.py`
**What:** Mirror `platform/launchd.py` using systemd user units:
- Unit file: `~/.config/systemd/user/ariaflow-aria2.service`
- `systemd_aria2_status()` — `systemctl --user is-active ariaflow-aria2`
- `install_aria2_systemd()` — write unit + `systemctl --user enable --now`
- `uninstall_aria2_systemd()` — `systemctl --user disable --now` + remove
- Session dir: `~/.aria2/` (same as macOS)
**Scope:** ~120 lines, 1 new file
**Note:** `systemctl --user` works without root. WSL2 supports systemd
since Sep 2022 (`systemd=true` in `/etc/wsl.conf`).

---

#### Step 6: Wire `install.py` — platform dispatch

**Where:** `src/aria_queue/install.py`
**What:** Replace the macOS-only `install_all()`/`uninstall_all()`/`status_all()`
with platform dispatch:
- `is_macos()` → existing Homebrew + launchd (unchanged)
- `is_windows()` → winget check for aria2 + Task Scheduler for auto-start
- `is_linux()` → check `aria2c` on PATH + systemd for auto-start
Remove `RuntimeError("install is only supported on macOS")`.
**Scope:** ~80 lines changed

---

#### Step 7: `routes/lifecycle.py` — platform lifecycle actions

**Where:** `src/aria_queue/routes/lifecycle.py:44`
**What:** Currently returns `macos_only` error on non-macOS. Add platform
dispatch: macOS → launchd, Windows → Task Scheduler, Linux → systemd.
**Scope:** ~40 lines changed

---

#### Step 8: Publish to PyPI

**Where:** `pyproject.toml`, GitHub Actions (new `.github/workflows/publish.yml`)
**What:**
- Verify `pyproject.toml` metadata (already has entry point, classifiers, URLs)
- Add `Operating System :: Microsoft :: Windows` and
  `Operating System :: POSIX :: Linux` classifiers
- Build: `python -m build` → wheel + sdist
- Publish: `twine upload dist/*` (or GitHub Actions on tag)
- Optional: GitHub Actions workflow that publishes on version tag push
**Scope:** ~1 line in `pyproject.toml` classifiers, ~30 lines workflow
**Result:** `pipx install ariaflow` works on all platforms

---

#### Step 9: Tests

**Where:** new `tests/test_platform.py`
**What:**
- Unit test `portalocker` locking on current platform
- Unit test `is_macos()`, `is_windows()`, `is_linux()` with `sys.platform` mock
- Unit test `platform/windows.py` with mocked `subprocess`
- Unit test `platform/linux.py` with mocked `subprocess`
- Verify `import aria_queue` doesn't crash when `sys.platform == "win32"`
**Scope:** ~120 lines, 1 new file

---

**Execution order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 (each = one commit)
**Total scope:** ~5 new files, ~6 modified files, ~500 lines, 1 new dependency (`portalocker`)

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
