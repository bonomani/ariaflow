# Plan

### [P1] Auto-start scheduler + pause/resume only

**What:** Scheduler starts automatically with `ariaflow serve`. Remove start/stop — user can only pause/resume.

**Why:** Discovery (P2) needs the scheduler always running. Start/stop adds complexity with no real benefit — the scheduler should process the queue whenever ariaflow is running.

**ASM state model change (Axis 2: Run):**
```
Before: idle → running → stop_requested → idle
                       → paused → running

After:  running ↔ paused
```

**Steps:**
1. `cli.py` — call `start_background_process()` automatically in `serve` command, before `server.serve_forever()`
2. `scheduler.py` — `start_background_process()` no longer needs to check "already running" (always starts). Remove `stop_background_process()`. Add `pause_scheduler()` and `resume_scheduler()` that set `state["paused"]`.
3. `routes/scheduler.py` — remove `post_scheduler_start`, `post_scheduler_stop`. Keep `post_pause`, `post_resume`.
4. `webapp.py` — remove `/api/scheduler/start` and `/api/scheduler/stop` from dispatch table
5. Update `routes/meta.py` — remove start/stop from API discovery
6. Update openapi.yaml via `make docs`
7. Update ASM state model doc
8. Update tests
9. Run all tests

**API change (breaking):**
- Remove `POST /api/scheduler/start`
- Remove `POST /api/scheduler/stop`
- Keep `POST /api/scheduler/pause`
- Keep `POST /api/scheduler/resume`

**Scope:** ~60 lines removed, ~20 lines added.
**Depends on:** Nothing.

---

### [P2] Peer discovery and auto-download

**What:** Background thread that browses `_ariaflow._tcp`, resolves peers, polls their `GET /api/torrents`, and auto-downloads new torrents.

**Why:** Enables automatic content distribution across ariaflow instances on the LAN without user intervention.

**Where:** New module `src/aria_queue/discovery.py`, new preferences in `contracts.py`, new endpoint in routes.

**How it works:**

1. **Browse** — continuously listen for `_ariaflow._tcp` on the local network
   - macOS/Windows: shell out to `dns-sd -B _ariaflow._tcp local` (long-running, outputs as peers appear)
   - Linux: shell out to `avahi-browse -r _ariaflow._tcp` (same pattern)
   - Parse stdout lines to detect new/removed peers

2. **Resolve** — for each discovered peer, get connection details
   - macOS/Windows: `dns-sd -L "{instance}" _ariaflow._tcp local` → host, port, TXT
   - Linux: `avahi-resolve-host-name {host}` or use output from `avahi-browse -r`
   - Read TXT: `path=/api`, `tls=0|1` → build base URL

3. **Poll** — periodically call each peer's `GET /api/torrents`
   - Interval: `peer_poll_interval_seconds` preference (default 60)
   - Returns list of available torrents with infohash, URL, metadata
   - Compare against local queue — skip already known infohashes

4. **Fetch** — for new torrents:
   - Check disk space (P3) — skip if over limit
   - Download `.torrent` file from peer → save to `torrent_dir`
   - Submit to local aria2 via existing `add_queue_item()` with `mode=torrent`
   - Track provenance: `source_peer` field on queue item

**New preferences (`contracts.py`):**
- `auto_discover_peers` — `false` (default off, opt-in)
- `peer_poll_interval_seconds` — `60` (how often to check peers)
- `peer_max_auto_downloads` — `5` (max torrents to auto-fetch per poll cycle)
- `peer_content_filter` — `""` (glob pattern, empty = accept all)
- `peer_allowlist` — `""` (comma-separated instance names, empty = accept all)

**New endpoint:**
- `GET /api/peers` — list of discovered peers with host, port, last_seen, torrent_count, status

**New module `discovery.py` (~200 lines):**
- `start_discovery(port)` — starts browse thread + poll thread
- `stop_discovery()` — kills browse process, stops poll thread
- `list_peers()` — returns current peer list
- `_browse_loop()` — runs `dns-sd -B` / `avahi-browse`, parses output, maintains peer dict
- `_resolve_peer(instance)` — runs `dns-sd -L` / uses avahi output, returns host:port:path
- `_poll_loop()` — periodic: for each peer, GET /api/torrents, filter, fetch new
- `_fetch_torrent(peer, torrent)` — download .torrent file, submit to queue

**Lifecycle:**
- Started in `cli.py` alongside scheduler (if `auto_discover_peers` is true)
- Stopped on shutdown (in `finally` block or signal handler)
- Paused/resumed with scheduler

**Scope:** ~200 lines new module, ~30 lines preferences, ~20 lines endpoint, ~20 lines cli.py.
**Depends on:** P1 (scheduler auto-start).

---

### [P3] Disk space management

**What:** Check available disk space before downloading. Stop auto-downloads when disk usage exceeds threshold.

**Where:** `src/aria_queue/scheduler.py` (check before submit), `contracts.py` (new preferences), `discovery.py` (check before auto-fetch).

**Why:** Without this, peer discovery (P2) could fill the disk. Also useful for regular downloads.

**New preferences:**
- `max_disk_usage_percent` — `90` (stop downloading when disk reaches this %)
- `torrent_dir` — `""` (default: `{config_dir}/torrents/`)
- `download_dir` — `""` (default: current working directory, same as aria2 default)

**How it works:**
```python
import shutil
usage = shutil.disk_usage(download_dir)
percent_used = (usage.used / usage.total) * 100
if percent_used >= max_disk_usage_percent:
    # skip download, log record_action with reason="disk_full"
```

**Where the check runs:**
- `scheduler.py` `process_queue()` — before `aria2_add_download()`: skip queued items if disk full
- `discovery.py` `_fetch_torrent()` — before auto-downloading from peer: skip if disk full
- `GET /api/health` — include `disk_usage_percent` in response for monitoring

**Steps:**
1. Add preferences to `contracts.py`
2. Add `_check_disk_space(path) -> bool` helper
3. Add check in `process_queue()` before submitting new downloads
4. Add `disk_usage_percent` to health endpoint
5. Wire into discovery module (P2)
6. Add tests
7. Run all tests

**Scope:** ~40 lines.
**Depends on:** Nothing (but P2 uses it).

---

### Implementation order

```
P1 → P3 → P2
```

- P1 first: simplifies the scheduler lifecycle before adding discovery
- P3 next: disk space check is a prerequisite for safe auto-downloads
- P2 last: depends on both P1 (scheduler always running) and P3 (disk safety)

**What:** Convert `routes.py` (1290 lines, 40 handlers) into a `routes/` package with one file per resource.
**Where:** `src/aria_queue/routes.py` → `src/aria_queue/routes/`
**Why:** 40 handlers in one file. Grouping by resource matches the API structure.
**Scope:** ~1290 lines moved, 0 logic changes.

**Pre-cleanup:**
- Remove dead `_session_fields` function (0 callers)

**Rule:** Only truly shared helpers go in `helpers.py`. Single-use helpers move with their handler.

Files:
- `routes/__init__.py` — re-exports all handlers (webapp.py dispatch unchanged)
- `routes/helpers.py` (~30 lines) — `_error_payload`, `_validate_item_id`, `_ALLOWED_URL_SCHEMES`
- `routes/downloads.py` (~300 lines) — get_status, get_archive, get_item_files, post_add, post_cleanup, post_item_files, post_item_action + single-use: `_parse_add_items`, `_validate_url`, `_validate_output_path`
- `routes/scheduler.py` (~170 lines) — get_scheduler, post_scheduler_start, post_scheduler_stop, post_pause, post_resume, post_preflight, post_ucc + single-use: `_resolve_auto_preflight_override`
- `routes/aria2.py` (~120 lines) — get_aria2_global_option, get_aria2_option, get_aria2_option_tiers, post_aria2_change_global_option, post_aria2_change_option, post_aria2_set_limits
- `routes/torrents.py` (~80 lines) — get_torrents, get_torrent_file, post_torrent_stop
- `routes/sessions.py` (~50 lines) — get_sessions, get_session_stats, post_session
- `routes/config.py` (~100 lines) — get_declaration, post_declaration, patch_declaration_preferences
- `routes/meta.py` (~250 lines) — get_health, get_api, get_docs, get_openapi_yaml, get_tests, get_events, get_log + single-use: `_api_discovery`, `_run_tests`, `_swagger_ui_html`, `_find_openapi_spec`
- `routes/lifecycle.py` (~120 lines) — get_lifecycle, post_lifecycle_action + single-use: `_lifecycle_payload`
- `routes/bandwidth.py` (~10 lines) — get_bandwidth, post_bandwidth_probe

**Implementation order:**
1. Remove dead `_session_fields` — cleanup before split
2. Create `routes/` directory + `__init__.py`
3. Create `routes/helpers.py` — shared by all other files, must exist first
4. Create `routes/meta.py` — no dependencies on other route files
5. Create `routes/config.py` — no dependencies on other route files
6. Create `routes/sessions.py` — no dependencies
7. Create `routes/bandwidth.py` — no dependencies
8. Create `routes/aria2.py` — no dependencies
9. Create `routes/torrents.py` — no dependencies
10. Create `routes/lifecycle.py` — no dependencies
11. Create `routes/scheduler.py` — no dependencies
12. Create `routes/downloads.py` — imports helpers (validate_url etc.)
13. Update `routes/__init__.py` with all re-exports
14. Delete old `routes.py`
15. Update `gen_openapi.py` to read from `routes/` package
16. Run tests — all 441 must pass

**Why this order:**
- Step 1: clean dead code before moving anything
- Step 2-3: foundation (package + shared helpers)
- Steps 4-12: each route file is independent — order doesn't matter, but meta first because it has the most single-use helpers to absorb
- Steps 13-14: switch over — __init__.py re-exports, delete old file
- Steps 15-16: update tooling + verify

_D1-D8 (private torrent distribution pipeline) implemented. See git history._

~~### [D1] Private torrent creation from downloaded file~~

**What:** New function `create_private_torrent(file_path, tracker_url)` that generates a `.torrent` with `private=1` flag and internal tracker URL.
**Where:** New module `src/aria_queue/torrent.py`
**Why:** After HTTP download, the file must be wrapped in a private torrent to distribute internally. aria2 cannot create torrents — needs external tool (`mktorrent` CLI or pure-Python bencode).
**Scope:** ~60 lines. New module. Preference `internal_tracker_url` in declaration.

Output: `.torrent` file bytes (base64-encodable for aria2 RPC).

### [D2] Seed after HTTP download (distribute mode)

**What:** New `distribute` flag on queue items. When an HTTP download completes and `distribute=true`:
1. Create private torrent (D1)
2. Submit to aria2 as torrent seed via `aria2_add_torrent(torrent_b64)`
3. Set `seed-ratio=0` (seed indefinitely)
4. Store torrent metadata (infohash, torrent path, tracker URL) on the item
**Where:** `src/aria_queue/queue_ops.py` (post_action), `src/aria_queue/scheduler.py` (_poll_tracked_jobs on complete)
**Why:** The node that downloaded via HTTP becomes the initial seeder.
**Scope:** ~40 lines. New item fields: `distribute`, `torrent_infohash`, `torrent_path`.
**Depends on:** D1

### [D3] Publish torrent availability via Bonjour

**What:** When a torrent is being seeded (distribute mode), register an additional Bonjour service per torrent:
- Service type: `_ariaflow-torrent._tcp`
- TXT records: package name, version, sha256, torrent_url, tracker, size
**Where:** `src/aria_queue/bonjour.py` (new function `advertise_torrent()`)
**Why:** Other ariaflow instances discover available packages via mDNS, download the `.torrent` file, and join the private swarm.
**Scope:** ~30 lines
**Depends on:** D2

### [D4] Serve .torrent files via HTTP

**What:** Serve created `.torrent` files at `GET /api/torrents/{infohash}.torrent` so other instances can download them after Bonjour discovery.
**Where:** `src/aria_queue/webapp.py` (new GET route)
**Why:** Bonjour TXT record points to `torrent_url` — backend must serve the file.
**Scope:** ~20 lines
**Depends on:** D1, D2

### [D5] List seeded torrents API

**What:** `GET /api/torrents` — returns list of locally seeded torrents with infohash, magnet, file info, tracker URL.
**Where:** `src/aria_queue/webapp.py` (new GET route)
**Why:** Frontend and other instances need to see what's available.
**Scope:** ~15 lines
**Depends on:** D2

### [D6] Declaration preferences for distribution

**What:** New preferences:
- `internal_tracker_url`: default `""` (empty = distribution disabled)
- `distribute_completed_downloads`: default `false`
- `distribute_seed_ratio`: default `0` (seed forever)
- `distribute_max_seed_hours`: default `72`
- `distribute_max_active_seeds`: default `10`
**Where:** `src/aria_queue/contracts.py`
**Scope:** ~25 lines

### [D7] aria2 daemon: disable DHT, PEX for private torrents

**What:** Add `--bt-force-encryption=true`, verify aria2 respects `private=1` flag (disables LPD, DHT, PEX automatically per BEP-27).
**Where:** `src/aria_queue/aria2_rpc.py` (aria2_ensure_daemon args)
**Scope:** ~3 lines

### [D8] Seed expiration policy

**What:** Scheduler checks active seeds each tick. Expires seeds that exceed age or count limit.
**Where:** `src/aria_queue/scheduler.py` (new `_expire_seeds()` in main loop)
**Why:** Without expiration: unlimited seeds, bandwidth, Bonjour spam, .torrent accumulation.
**Scope:** ~30 lines

On expiration:
1. `aria2_remove(gid)` — stop seeding
2. Deregister Bonjour service for that torrent
3. Delete `.torrent` file
4. **Never delete the downloaded file**
5. Update item: `distribute_status = "expired"`

New preferences (D6):
- `distribute_max_seed_hours`: default 72
- `distribute_max_active_seeds`: default 10

### Implementation order

```
D6 → D7 → D1 → D2 → D3 → D4 → D5 → D8
```

D6 (preferences) and D7 (daemon args) first — foundation.
D1 (torrent creation) — core capability.
D2 (seed after download) — connects HTTP download to torrent.
D3 (Bonjour publish) — announces to network.
D4 (serve .torrent) — enables other instances to download the torrent file.
D5 (list API) — visibility.
D8 (expiration) — lifecycle cleanup.

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
