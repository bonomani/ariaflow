# Plan

### [P1] BG-3: Add explicit response schemas to openapi.yaml

**What:** Extend `scripts/gen_openapi.py` to emit explicit `properties` for each GET endpoint's response schema (instead of `{type: object}`). Source the schemas from a new dict module.

**Where:**
- New: `src/aria_queue/openapi_schemas.py` — dict mapping path → response schema properties
- Modified: `scripts/gen_openapi.py` — read schemas, inject into generated spec
- Generated: `openapi.yaml` and `src/aria_queue/openapi.yaml` — now contains typed responses

**Why:** Resolves BG-3 reported by the frontend. Current openapi.yaml has empty response schemas so the frontend hand-maintains `EXPECTED_FIELDS` per endpoint. New backend fields (e.g. the metrics I just added: `uptime_seconds`, `sse_clients`, `errors_total`) are silently invisible to the frontend until someone remembers to update the frontend's hand-maintained list.

**Design:**

`openapi_schemas.py` layout (single source of truth):
```python
RESPONSE_SCHEMAS = {
    "GET /api/health": {
        "status": {"type": "string"},
        "version": {"type": "string"},
        "disk_usage_percent": {"type": "number"},
        "disk_ok": {"type": "boolean"},
        "requests_total": {"type": "integer"},
        "bytes_sent_total": {"type": "integer"},
        "bytes_received_total": {"type": "integer"},
        "errors_total": {"type": "integer"},
        "uptime_seconds": {"type": "number"},
        "started_at": {"type": "string"},
        "sse_clients": {"type": "integer"},
    },
    "GET /api/scheduler": {
        "status": {"type": "string"},
        "running": {"type": "boolean"},
        "paused": {"type": "boolean"},
        ...
    },
    ...
}
```

`gen_openapi.py` changes:
1. Import `RESPONSE_SCHEMAS` from `openapi_schemas`
2. When emitting each endpoint's `responses.200.content.application/json.schema`, look up `"{METHOD} {path}"` in the dict
3. If present, emit `type: object` + `properties: {...}` + `required: [keys]`
4. If missing, fall back to current empty object (so partial adoption works)

**Test coverage:**
- New test `test_openapi_schemas_cover_all_get_endpoints` — assert every GET endpoint in webapp dispatch has an entry in `RESPONSE_SCHEMAS`
- New test `test_openapi_schema_fields_match_handler_output` — for a few representative endpoints (`/api/health`, `/api/scheduler`), actually call the handler with mocks and compare keys to declared schema
- This gives compile-time enforcement that new fields force a schema update

**Scope:** ~150 lines for schemas (covering ~15 GET endpoints), ~30 lines in generator, ~40 lines of tests.

**Not in scope:**
- POST request body schemas (BG-3 only mentions responses; can be separate item)
- Path parameter schemas (already handled by existing generator)
- Auto-discovery from handler source (too fragile per earlier analysis)

**Depends on:** Nothing.

**Verification:**
1. Run `python scripts/gen_openapi.py`
2. Check `openapi.yaml` has `properties` on health/scheduler/status endpoints
3. Frontend (separate session) can remove `EXPECTED_FIELDS` hand-maintained dict

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
