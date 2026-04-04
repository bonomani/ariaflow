# Plan

No open items.

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
