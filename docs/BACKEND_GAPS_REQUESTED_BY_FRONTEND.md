# Backend Gaps Requested by Frontend

> **Ownership:** Authored and maintained by the **ariaflow-dashboard** frontend agent.
> The backend agent should read this file at session start, fix open items,
> and move them to the Resolved section when done — but should NOT add or
> delete entries (that's the frontend's responsibility).
>
> **Single source of truth — no mirrors.**
>
> **Pairing rule:** Every open backend gap should have a paired frontend gap in
> `../ariaflow-dashboard/FRONTEND_GAPS.md` marked `Blocked by: BG-N` (unless it's
> pure infrastructure with no user-visible counterpart — then `Blocks frontend gap: (none)`).

## Open (1)

### BG-57: `/api/status` summary should be of the *unfiltered* queue

**Paired frontend gap:** FE-47 (no FE change once backend swaps the summary source)

**Symptom:** with any non-`all` queueFilter active, every count chip
on the filter bar except the active one reads 0. The operator on
"Active" can't see how many items are queued/error/awaiting_confirmation
without switching filters.

**Root cause** (`packages/api/src/routes/status.ts:158-159`):

```ts
items: filtered,
summary: summarizeQueue(filtered),   // ← also filtered
```

When the FE sends `?status=active`, `filtered` excludes everything
else, so `summarizeQueue` returns `{ active: N }` and zero for the
rest. The FE filterCounts getter trusts the backend summary, so the
filter bar reads 0 for awaiting_confirmation, queued, error, etc.

**Fix:** summarize the unfiltered queue, filter only `items`:

```ts
items: filtered,
summary: summarizeQueue(items),     // unfiltered, full counts
```

The client expects `summary` to describe the *queue*, not the
visible-after-filter slice. The same applies to FE's "Confirm" badge
that reads `summary.awaiting_confirmation` — currently invisible
unless the operator already filters to that bucket.

**Acceptance:**

1. Add 1 queued + 1 active + 1 awaiting_confirmation item.
2. GET `/api/status?status=active` → `summary.queued === 1`,
   `summary.awaiting_confirmation === 1`, `items.length === 1`
   (the active one).
3. Existing tests pass — `summary` is unchanged when statusFilter
   is empty.

**FE follow-up:** none. The FE already trusts the backend summary
for the filter bar.

---



<details>
<summary>BG-56 (resolved) — original frontend brief retained for context</summary>

### BG-56: Folder operations within `<download_dir>` (rename / move / delete / clean)

**Paired frontend gap:** FE-46 (Downloaded tab actions UI)

**Roadmap doc:** `../ariaflow-dashboard/docs/POST_DOWNLOAD_LIFECYCLE.md` — Phase 1.

**Goal:** let the operator manipulate files **inside the ariaflow-managed
download folder** from the dashboard. Out of scope: anything outside
that folder. Operators have Finder / nautilus for the rest.

**Scope guardrails — non-negotiable:**

1. Every path is validated to resolve inside `<download_dir>`
   (canonicalize, follow symlinks, reject `..` traversal, reject
   absolute paths outside).
2. ariaflow never touches the wider filesystem.
3. Recursive directory operations require an explicit `recursive: true`
   flag in the request body.
4. All operations append to the action log with the original and
   resulting paths so any change is auditable.
5. After a successful op, sync the affected queue history rows:
   - rename/move → update `output_path`
   - delete → flag the row `file_present_on_disk: false` (don't delete
     the row — the URL/history record stays)

**New endpoints:**

```
POST   /api/files/rename       { path, new_name }                → 200 / 409
POST   /api/files/move         { path, new_subdir }              → 200 / 409
DELETE /api/files              { path, recursive? }              → 204
POST   /api/files/clean        { older_than_days?, status? }     → 200 + summary
GET    /api/files                                                → 200 + listing
```

`GET /api/files` is the inspector: walks `<download_dir>` (single
level by default; nested with `?recursive=true` capped at depth 3),
returns:

```json
{
  "ok": true,
  "files": [
    {
      "path": "/Users/bc/Downloads/ubuntu.iso",
      "rel_path": "ubuntu.iso",
      "size": 6553600000,
      "modified_at": "2026-04-12T18:34:00Z",
      "type": "file",
      "history_match": {
        "item_id": "abc123",
        "url": "https://...",
        "downloaded_at": "2026-04-12T18:34:00Z"
      }
    }
  ]
}
```

The `history_match` field is the join with the queue history — null
for files that ariaflow didn't download (manually-placed files etc).
This is what powers the "On disk + no history" row state in the
Downloaded tab.

**Cleanup recipes:** `POST /api/files/clean` accepts:

- `{ status: "complete", older_than_days: 30 }` — delete files
  for completed items older than N days
- `{ status: "error" }` — delete files associated with errored items
  (cleanup of failed retry artifacts)
- `{ orphaned: true }` — delete history rows where the file is
  missing on disk (reconcile, no disk side effect)

**Acceptance:**

1. POST `/api/files/rename` with `{path: "/Users/bc/Downloads/ubuntu.iso", new_name: "ubuntu-2604.iso"}`:
   - 200 with new path
   - file renamed on disk
   - queue history row's `output_path` updated
   - action log: `outcome: "renamed", target: files`
2. POST with a path *outside* `<download_dir>`: 400 `path_outside_download_dir`.
3. POST with `..` in path: 400 `path_traversal_rejected`.
4. DELETE on a non-empty directory without `recursive: true`: 409.
5. GET `/api/files` returns listing matching `ls <download_dir>`
   (size, mtime), with `history_match` populated for ariaflow-known
   downloads.
6. POST `/api/files/clean` with `{status: "complete", older_than_days: 30}`:
   removes only matching files, leaves recent ones, returns summary
   `{ deleted: N, freed_bytes: M }`.

**FE follow-up (FE-46):**

- Downloaded tab gains per-row actions: Rename, Move (subdir picker),
  Delete (with confirm)
- Bulk action bar: Clean… → modal with the recipes
- Disk-usage chip in the tab header: total, by status
- Three row states from `GET /api/files`:
  - on disk + history_match → full record
  - on disk + no history_match → "found in folder, source unknown"
  - not on disk + history → "missing from disk" with [Re-download] [Forget]

**Open questions for the backend agent (small):**

- What's the canonical way to read `<download_dir>` from the
  declaration? (suspect `prefValue(declaration, "download_dir")` —
  same as scheduler/probes uses)
- Should rename collide-detect against existing files and require an
  explicit overwrite flag, or just 409 on collision? (recommend 409,
  no implicit overwrite)

</details>

---

<details>
<summary>BG-55 (resolved — Tier 1 + decision endpoints; Tier 2/3 deferred) — original frontend brief retained for context</summary>

### BG-55: Verify-then-confirm flow for re-add of an already-downloaded URL

**Paired frontend gap:** FE-45 (UI for the new `awaiting_confirmation` state + three decision actions)

**Builds on:** BG-54 (drops `allow-overwrite: true`, makes the safe default land first).

**Why this matters:** ariaflow downloads are typically multi-GB. A
mistaken re-add silently wastes a full transfer in bandwidth, time,
and disk. BG-54's `.1` auto-rename avoids data loss but still pays
the full re-download cost. For huge files, the operator wants a
chance to say "I already have it, skip" before any bytes flow.

**Design — filesystem-first verification, then ask the operator:**

The download folder is ground truth. The queue history is *supplementary
metadata* (when did we last fetch, what was the ETag) — not the primary
existence check. This catches files downloaded outside ariaflow
(manual wget/curl, browser, prior installation, files the operator
copied in) which a queue-history-only approach would miss.

When `queue/ops.add()` runs (and the URL has no live duplicate), the
gate is:

1. **Determine expected filename**:
   - **HEAD url** if `verify_existing_strategy` ≥ Tier 2 → trust
     `Content-Disposition: attachment; filename="..."` first, fall
     back to URL last path segment.
   - **Otherwise** (Tier 1 only) → URL last path segment
     (best-effort; may differ from what aria2 will actually write).
2. **Stat `<download_dir>/<expected_filename>`**.
3. Outcomes:

| File at expected path | Size matches HEAD `Content-Length` | Outcome |
|---|---|---|
| no | — | `queued` (no prompt; nothing to confirm) |
| yes | yes (or HEAD skipped) | `awaiting_confirmation` |
| yes | no | depends on strategy: Tier 2 → `awaiting_confirmation` with `remote_changed: true`; Tier 1 → `queued` (assume re-fetch wanted) |

4. **Enrichment from queue history** — when an `awaiting_confirmation`
   row is created, look up any prior terminal-status item for the same
   URL and attach detail:
   - "Last downloaded by ariaflow on `<date>`" (if history match)
   - "Source unknown — file present in folder but never downloaded by
     ariaflow" (if no history match)
   - Recorded `prior_item.remote_etag` for comparison against HEAD
     response

   The history is a UX hint to the operator, not the gate itself.

**New queue status:** `awaiting_confirmation` (added to BG-30's
8-status set → 9). Surfaces in `summary.awaiting_confirmation` count
and in `items[].status`.

**Three decision endpoints:**

```
POST /api/downloads/:id/confirm    → status flips to queued, dispatched
                                      with allow-overwrite=true (per-item
                                      override) so the existing path is
                                      reclaimed
POST /api/downloads/:id/skip       → moves to removed, reason
                                      "duplicate_skipped"; no bytes
                                      transferred
POST /api/downloads/:id/rename     → moves to queued, dispatched without
                                      overwrite so aria2 auto-renames to
                                      <name>.1; both files coexist
```

Each decision lands an action-log entry so the operator's choice is
auditable.

**New persisted fields on QueueItemRecord (UX enrichment only — not load-bearing for the gate):**

- `output_path: string` — absolute path the file was actually written
  to. Captured at completion via `tellStatus(gid).files[0].path` in
  the existing `scheduler/poll.ts` reconcile hook before aria2
  garbage-collects the GID. Used by the FE to render "Last downloaded
  here on `<date>`" hints. Backfill: items completed before this field
  landed have it null — gate still works because gate stats the
  filesystem directly, not this field.
- `remote_etag?: string` — captured at completion via aria2's
  `responseHeaders` if available. Optional. Compared against fresh
  HEAD response when Tier 2 verification fires.
- `remote_last_modified?: string` — same source, optional.

**Why filesystem-first matters more than queue history:**

A queue-history-only design misses files downloaded outside ariaflow
(manual wget, browser, previous installation, operator copy-in).
Those are common in real workflows — operators often have an existing
download collection from before they installed ariaflow. The gate has
to treat the folder as authoritative.

**New declaration preferences:**

- `verify_existing_strategy`: `"local_only" | "local_and_remote_head" | "local_and_sampled_hash" | "off"` (default `"local_only"`)
- `confirm_redownload_default_action`: `"prompt" | "skip" | "rename" | "redownload"` (default `"prompt"`) — for non-interactive callers (CLI / scripted batch adds), the FE-less path needs a default

**Verification rigor — none of these prove "same file" absolutely.**
They produce a confidence judgement appropriate to ariaflow's
single-operator self-hosted use case. The full-file hash isn't an
option here: an 8 GiB file would take minutes to read from disk, which
is unacceptable as a UX gate.

| Strategy | Method | Cost | Catches | Misses |
|---|---|---|---|---|
| `local_only` | `fs.stat(path).size === totalLength` | ~0ms | gone / truncated / wrong size | content corruption with matching size, manual replacement |
| `local_and_remote_head` | + `HEAD url`, compare `Content-Length` / `ETag` / `Last-Modified` | ~100ms (1 round trip, no body) | server has newer version | local corruption since download |
| `local_and_sampled_hash` | + hash 4 KiB at head / middle / tail (aria2 piece boundaries) | ~ms (3 disk reads) | most local corruption | adversarial same-size byte flips at non-sampled offsets |
| `off` | skip verification entirely | 0ms | nothing | always assume "have it" or "don't have it" per a fallback rule |

Default `local_only` is right for the common case (single operator,
single machine, file system trusted). Operators on shared FS or who
care about server-side updates should pick a stricter tier.

**Acceptance:**

1. Add a download. Let it complete. Persisted item has
   `output_path` populated.
2. Add the same URL again. The new item appears with
   `status: "awaiting_confirmation"`.
3. Three actions all work: confirm dispatches with overwrite, skip
   removes, rename dispatches without overwrite (aria2 produces `.1`).
4. Delete the file on disk. Re-add: verification fails, item goes
   straight to `queued` with action-log reason
   `verify_local_missing`.
5. Set `verify_existing_strategy: "local_and_remote_head"`. Add a URL
   whose server returns a different ETag than recorded: item goes
   straight to `queued` with reason `remote_etag_changed`. Operator
   sees in the activity log why re-download fired.
6. Set `confirm_redownload_default_action: "skip"`. Re-add via CLI
   without the FE: item goes to `removed` automatically with reason
   `duplicate_skipped` instead of waiting for a prompt.

**FE follow-up (FE-45):**

- Render an `awaiting_confirmation` row variant in the queue panel
  with a banner: "Already have <name> (<size>) at <path>. [Skip]
  [Re-download] [Add as .1]"
- (If `remote_changed: true` ever surfaces) banner reads
  "Server has a newer version of <name> (ETag changed). [Re-download]
  [Skip]"
- Wire three new item actions to the new endpoints.
- Add the new status to `ITEM_STATUSES` and the filter buckets.
- Surface `awaiting_confirmation` count in the filter bar (e.g.
  between `active` and `paused`).

</details>

---



<details>
<summary>BG-54 (resolved) — original frontend brief retained for context</summary>

### BG-54: Drop hardcoded `allow-overwrite: true` in dispatch — let aria2 rename or fail safely

**Paired frontend gap:** FE-44 (no FE change required if default flips to safe behavior; FE may want a "force re-download" toggle later)

**Symptom:** re-adding the same URL of an already-downloaded file
silently overwrites the existing file. No warning, no `.1` rename, no
indication to the operator that the previous download is being
clobbered. Confirmed via the user's recent test (Ubuntu ISO added
twice → both completed at the same path with different aria2 GIDs).

**Root cause** (`packages/core/src/aria2/dispatch.ts:73-79`):

```ts
const options: Aria2Options = {
  "max-download-limit": aria2SpeedValue(opts.capBytesPerSec),
  "allow-overwrite": "true",   // ← always on, no override
  continue: "true",
  "max-tries": String(opts.prefs.max_tries ?? 5),
  "retry-wait": String(opts.prefs.retry_wait ?? 10),
};
```

`allow-overwrite: true` is unconditionally injected. This:

1. **Defeats `auto-file-renaming: true`** (aria2's default). The rename
   logic only fires when overwrite is denied. With overwrite forced,
   the renaming code path is dead — visible as both options coexisting
   in `GET /api/aria2/option?gid=X` despite being mutually exclusive.
2. **Silent data loss on re-add.** A previously-completed file is
   overwritten with no operator confirmation. Combined with the
   intentional "don't dedupe terminal items" behavior in
   `queue/ops.ts`, the operator can lose data with no signal.
3. **Couples to `continue: true` confusingly.** With overwrite=true,
   `continue` only matters for partials *of the current run*; cross-run
   resume against a fully-downloaded file just overwrites instead of
   noop'ing.

**Two coherent options:**

A. **Drop `allow-overwrite: true` entirely.** aria2 falls back to its
   default (`false`), and `auto-file-renaming: true` (also default)
   gives `.1` / `.2` renames automatically. Operator gets non-destructive
   behavior on re-add. Resume of a partial via `continue: true` still
   works because aria2 resumes from the `.aria2` control file
   regardless of overwrite setting.

B. **Make it a preference.** Add `allow_overwrite_existing` to the
   declaration vocabulary, default `false`. Operator who wants the
   current behavior can opt back in. Backend reads
   `prefValue(declaration, "allow_overwrite_existing", false)` and
   sets the aria2 option accordingly.

**Recommendation: option A.** No new pref surface, principle of
least surprise, aria2 defaults already produce the safe behavior.

**Acceptance:**

1. Add a download. Let it complete.
2. Add the same URL again.
3. Old file untouched on disk; new download arrives as
   `<name>.1` (auto-file-renaming kicks in). Action log shows
   `outcome: "added", detail: { renamed_to: "<name>.1" }` if backend
   wants to expose that, but not required.

**FE follow-up:** none for option A. Optionally surface a
"force re-download" item action in the future if operators ask
for it (would set `allow-overwrite=true` per-item via `select_file`-
style override). Not required now.

</details>

---

<details>
<summary>BG-53 (resolved) — original frontend brief retained for context</summary>

### BG-53: Per-download `max-download-limit` not refreshed on probe; in-flight transfers drift below the displayed cap

**Paired frontend gap:** FE-43 (FE renders the live cap correctly; just needs the per-download limit to follow it)

**Symptom:** dashboard CAP card reads `5.7 Mbps` but a single in-flight
download has `max-download-limit: 625000` bytes/s = 5.0 Mbps. The
download is silently throttled below the operator's declared cap.
Inspecting via `GET /api/aria2/option?gid=…` shows the stale value
sticking around for the lifetime of the transfer.

**Root cause — two parallel cap mechanisms drift apart:**

1. **Per-download** `max-download-limit` (`aria2/dispatch.ts:74`) is
   computed from `capBytesPerSec` at the moment the item is dispatched
   (`addUri` time). It never moves after that for an in-flight gid.
2. **Aria2 global** `max-overall-download-limit` is re-set on every
   probe via `bandwidth.ts:28`
   (`setMaxOverallDownloadLimit(probeRec.cap_bytes_per_sec)`).

When a probe lands a new value (manual probe today; once BG-52 ships,
periodic too), the global is refreshed but the per-download is not.
aria2 enforces `min(per-download, global)`, so the stale per-download
silently wins for any transfer that started before the new probe.

**Requested behaviour:** alongside `setMaxOverallDownloadLimit`, walk
every active aria2 gid and call
`aria2.changeOption(gid, { 'max-download-limit': aria2SpeedValue(cap) })`.
The helper at `core/src/aria2/methods.ts:99` already exists. Apply
it from:

- `routes/bandwidth.ts:28` (manual `POST /api/bandwidth/probe`) — fix today
- The periodic auto-probe loop once BG-52 lands

**Acceptance:**

1. Start a download, observe `GET /api/aria2/option?gid=X` returning
   `max-download-limit` matching `bw.cap_bytes_per_sec`.
2. Run a manual probe (`POST /api/bandwidth/probe`) that yields a
   different cap (changing reserve % is enough to shift it).
3. Re-query `GET /api/aria2/option?gid=X`: `max-download-limit` now
   matches the new cap. Action log shows
   `outcome: "changed", target: aria2.options, detail: {gid, max_download_limit}`.

**Alternative (simpler, possibly preferable):** drop per-download
`max-download-limit` entirely. The aria2 global cap covers every
transfer; per-download is redundant when there's no per-item budgeting
logic. Lower complexity, no drift.

**FE follow-up:** none — FE already renders the live cap.

</details>

---

<details>
<summary>BG-52 (resolved) — original frontend brief retained for context</summary>

### BG-52: Bandwidth probe never re-runs — `bandwidth_probe_interval_seconds` is dead

**Paired frontend gap:** FE-42 (FE renders "overdue" warning correctly; just waiting for probe to actually re-fire)

**Symptom on the dashboard:** with a download in flight, the bandwidth
panel shows `Probed 8m 13s ago` with an `overdue` chip. `auto every 180s`
is configured. The probe never re-runs unless the operator clicks
"Run probe" manually.

**What's broken:**

1. Operator declares `bandwidth_probe_interval_seconds: 180` (default,
   declaration.ts:44).
2. Backend reads this value:
   - In `deriveWaitReason` (`status.ts:93`) to compute probe staleness
     for `bandwidth_probe_pending`
   - In `_scheduler_status.ts:49` to expose it on the wire
3. **Nothing schedules a periodic probe.** The probe runs only at
   `_scheduler_controller.ts:87` (one-shot at scheduler preloop) and
   on manual `POST /api/bandwidth/probe`.
4. After 180s, `deriveWaitReason` correctly classifies the probe as
   stale → `bandwidth_probe_pending`. Except wait_reason is null while
   scheduler is `running`, so the operator only sees "stale" via the
   FE's `bw_probe_stale` derivation against `last_probe_at`.

**Three coherent options:**

A. **Periodic auto-probe (recommended).** A timer in the scheduler
   controller re-runs `runBandwidthProbe` every
   `bandwidth_probe_interval_seconds`. Skip if scheduler is `paused`
   or `stopped`. While `running` (active download), the probe will
   compete with download traffic — that's expected; networkquality is
   short and the operator can disable auto-probe via interval=0 if it
   matters.

B. **Idle-only probe.** Re-probe only when scheduler enters/leaves
   idle, plus on `pause`/`resume`. Avoids contention but the cap
   value can grow stale during a long-running download.

C. **Remove the interval pref.** If periodic probing is intentionally
   not implemented, drop `bandwidth_probe_interval_seconds` from the
   declaration vocabulary so the FE doesn't surface a knob with no
   effect, and rename the staleness threshold to something like
   `bandwidth_probe_max_age_seconds` to make the semantics honest.

**Acceptance:**

1. With `bandwidth_probe_interval_seconds: 60`, leave the dashboard
   open for 5 minutes during an active download.
2. The bandwidth panel's "Probed X ago" timestamp ticks back to a
   small value at least every 60s; `overdue` chip never fires.
3. Action log shows `bandwidth_probe` entries at the configured
   cadence with `reason: "scheduler_periodic"` (or similar).
4. Setting interval=0 disables periodic probing; manual probe still
   works.

**FE follow-up:** none. The FE already renders whatever
`last_probe_at` reports.

</details>

---

<details>
<summary>BG-51 (withdrawn — false alarm) — original brief retained for context</summary>

### BG-51 (WITHDRAWN): Scheduler stuck `idle` (no wait_reason) after Add kicks it

Filed 2026-05-06 then withdrawn the same day. Operator initially
reported "stays like that forever" but both items did dispatch and
complete within ~12s. The auto-kick logic at `downloads.ts:56-64`
worked correctly; the perceived hang was just dispatch latency.

No action needed.

</details>

---

<details>
<summary>BG-51 (original brief)</summary>

### BG-51: Scheduler stuck `idle` (no wait_reason) after Add kicks it

**Paired frontend gap:** FE-41 (no FE change — backend dispatch hole)

**Symptom on the dashboard (v0.1.515):**

1. Queue empty, scheduler idle (`idle · queue empty`).
2. Operator adds a download (https://releases.ubuntu.com/26.04/ubuntu-26.04-desktop-amd64.iso).
3. Backend POST `/api/downloads` succeeds; queued item appears.
4. Backend's auto-kick logic (`downloads.ts:56-64` —
   `!s.running && !s.paused && created.some(c => !c.duplicate)` →
   `callStartScheduler`) fires.
5. Badge transitions to plain `idle` (no wait_reason). **Item stays
   queued forever.** No retry, no error, no bandwidth probe pending.

The `wait_reason` is `null` despite an idle scheduler with a queued
item. Per `deriveWaitReason` (status.ts:83-98), `null` means: aria2
reachable + preflight ok + disk ok + queue NOT empty + probe fresh →
nothing should be blocking dispatch. Yet nothing dispatches.

**Hypothesis:**

- `callStartScheduler` sets intent=running and the loop runs one
  iteration but exits without dispatching (no apparent reason from the
  derivation contract).
- OR the loop is running (running=true, no active_gid) but the
  dispatcher tier isn't actually picking the queued item up.

The wire contract says "idle + null wait_reason" should never persist
when there's work to do. Either the loop is exiting early (and a
wait_reason should reflect why), or the dispatcher isn't tied to the
queue change event.

**Reproduction:**

1. Start with empty queue, scheduler running (idle · queue empty).
2. POST a single non-duplicate URL to `/api/downloads`.
3. Wait. Item should transition to `active` within seconds (aria2
   gid assigned). Currently it stays `queued` indefinitely.

**Acceptance:**

1. After Add into a drained-idle scheduler, the queued item enters
   `active` (or `discovering` for metalinks/torrents) within one
   scheduler tick.
2. If for any reason the loop can't dispatch, `wait_reason` reflects
   the reason (new value if needed, e.g. `loop_not_running`).
3. The "idle + null wait_reason + non-empty queue" combination is
   impossible by contract.

No FE change needed: dashboard renders whatever `state.scheduler_status`
and `state.wait_reason` report. Once the dispatch hole is closed, the
operator sees `running` (or a meaningful wait_reason) instead of
silent idle.

---



<details>
<summary>BG-50 (resolved) — original frontend brief retained for context</summary>

### BG-50: `deriveSchedulerStatus` should report `paused` when paused, even if loop is drained

**Paired frontend gap:** FE-40 (no FE change needed — pure backend derivation tweak)

**Symptom on the dashboard:** when the scheduler is `idle` (loop drained,
intent=running, session open) and the operator clicks **Pause**:

1. FE dispatches `POST /api/scheduler/pause`.
2. Backend persists `state.paused = true` ✓
3. BG-49 envelope returns `state.scheduler_status: 'idle'` ✗
4. Badge stays `idle`. The Pause click looks like a no-op to the operator
   even though the dispatch-paused flag *was* set and *will* block the
   next dispatch (e.g. when a new download is added).

**Root cause** (`packages/core/src/scheduler/status.ts:40-52`):

```ts
if (intent === "stopped") return "stopped";
if (!state.running) {
  return hasOpenSession ? "idle" : "starting";   // returns BEFORE checking paused
}
if (state.paused) return "paused";
return state.active_gid ? "running" : "idle";
```

The `!state.running` branch fires first and short-circuits, so `paused` is
only ever surfaced while the loop is actively dispatching.

**Operator mental model:** "I clicked Pause. The dispatcher is paused.
Future work won't fire until I resume. The badge should say `paused`."
Whether the loop happens to be in-cycle right now is an implementation
detail.

**Requested behaviour:** check `paused` before the `!running` branch:

```ts
if (intent === "stopped") return "stopped";
if (state.paused) return "paused";   // NEW: persistent intent wins
if (!state.running) {
  return hasOpenSession ? "idle" : "starting";
}
return state.active_gid ? "running" : "idle";
```

After this change, `paused` reflects the persistent dispatch-paused flag
regardless of whether the loop is mid-iteration or drained.

**Acceptance:**

1. With `intent=running, running=false, session_id=set, paused=true` →
   `deriveSchedulerStatus` returns `'paused'` (was `'idle'`).
2. With `intent=running, running=true, paused=true` → still `'paused'`
   (unchanged).
3. Existing tests for `running` / `idle` / `starting` / `stopped` keep
   passing — only the new `paused-while-drained` case changes.
4. /api/scheduler/pause and /api/scheduler/resume responses (BG-49
   envelope) reflect the new derivation.

No FE change needed once this lands. The dashboard renders whatever
`state.scheduler_status` reports.

</details>

---



<details>
<summary>BG-49 (resolved) — original frontend brief retained for context</summary>

### BG-49: Return canonical post-action state from /api/scheduler/{start,stop,pause,resume}

**Paired frontend gap:** FE-39 (FE currently guesses `scheduler_status` optimistically after each action)

**Why:** Today the four scheduler action endpoints return four different
flat shapes:

| Route | Returns |
|---|---|
| `POST /api/scheduler/start` | `{ok, started, running, ...}` |
| `POST /api/scheduler/stop` | `{ok, stopped, ...}` |
| `POST /api/scheduler/pause` | `{ok, paused: true, _rev}` |
| `POST /api/scheduler/resume` | `{ok, paused: false, _rev, ...}` (no `resumed` field — success means `paused === false`) |

The FE just shipped a fix (v0.1.508) that handles all four explicitly,
but it still has to *guess* what `scheduler_status` will become because
the response doesn't include it. The optimistic enum write
(`scheduler_status='starting'` after /start, `'paused'` after /pause,
etc.) is a best-effort patch until SSE / next poll arrives.

This guess can be wrong: e.g. /start on a system that immediately has
work to do skips 'starting' and goes to 'running'. The FE flickers
'starting → running'. Worse, on /resume the FE has to inspect
`currentTransfer` to decide between 'running' and 'idle' — duplicating
backend logic that already lives in `deriveSchedulerStatus`.

**Proposal:** every scheduler action response includes the canonical
post-action state envelope, so the FE can splat it into `lastStatus.state`
and skip optimism entirely:

```json
{
  "ok": true,
  "started": true,
  "state": {
    "scheduler_status": "starting",
    "running": true,
    "dispatch_paused": false,
    "session_id": "...",
    "_rev": 42
  }
}
```

Same `state` block on /stop, /pause, /resume. Existing flat fields
(`started`, `stopped`, `paused`) stay for back-compat for one release.

**Impact:** FE `schedulerAction()` and `_pauseResume()` can drop the
optimistic-write logic (~15 lines) and the `currentTransfer`-based
'running vs idle' guess on /resume. UI flips instantly to the *real*
post-action enum, not a guess.

**Acceptance:**

1. All four routes return `state: { scheduler_status, running, dispatch_paused, session_id, _rev }`.
2. The `state` block matches what `GET /api/status` would return immediately after.
3. Tests: assert `state.scheduler_status === 'starting'` after /start, `=== 'stopped'` after /stop, `=== 'paused'` after /pause, `=== 'running' | 'idle'` after /resume (depending on whether there's an active gid).

</details>

---

<details>
<summary>BG-48 (resolved) — original frontend brief retained for context</summary>

### BG-48: Rename `ucc` action verb + endpoint to `contract`

**Paired frontend gap:** FE-38 (display-only alias `actionDisplay()` already
ships; will be removed once backend rename lands)

**Why:** "UCC" is an opaque acronym in the UI. The FE already
relabels every appearance to "contract" (section header, button,
activity-log rows, filter dropdown) via a small alias map, but the
wire still surfaces `ucc` in:

- `POST /api/scheduler/ucc`
- action-log `entry.action === 'ucc'`
- `meta.contract` field on the trace response (already named
  contract — confirms the operator-facing word)
- `/api/_meta` registry path

So we have a name split: backend says "ucc", everything user-facing
says "contract". The alias closes the gap on the FE side, but it's
brittle — every new tool, log filter, or external dashboard hitting
the API has to re-learn the same mapping.

**Requested:**

1. Add a parallel `POST /api/scheduler/contract` endpoint that
   does exactly what `/ucc` does today.
2. Have the action log emit `action: "contract"` for new runs.
3. Mark `/api/scheduler/ucc` as deprecated in the OpenAPI spec
   (back-compat — keep accepting it for one release, then drop).
4. Update `meta.contract` (already correctly named) to also live as
   `meta.kind: "contract"` if that field structure makes sense to
   you — pure-cosmetic detail, not blocking.

**FE follow-up after this lands:** drop `actionDisplay()` and the
`'ucc' → 'contract'` mapping; FE-38 closes.

**Naming notes:** "contract" matches the existing `meta.contract`
field, the section subhead "Contract execution trace", and the
operator's mental model ("did the contract converge?"). Other
candidates considered and rejected: "selfcheck" (too generic),
"audit" (audit log already overloaded in the project), "verify"
(implies a one-shot pass/fail rather than the steady-state-reach
semantics that UCC actually has).

</details>

<details>
<summary>BG-47 (resolved) — original frontend brief retained for context</summary>

### BG-47: Don't gate scheduler on bandwidth probe when queue is empty

**Paired frontend gap:** FE-37 (no FE change needed — pure backend
priority reorder)

**Symptom seen on the dashboard:** with an empty queue and a probe
that hasn't run yet, the scheduler badge reads
`idle · bandwidth probe pending`. That's misleading — there's
nothing to schedule, so the probe state is irrelevant. The right
read is `idle · queue empty`.

**Root cause:** `deriveWaitReason()` (BG-40, in
`packages/core/src/scheduler/status.ts`) currently classifies in
this priority order:

```
aria2_unreachable
preflight_blocked
disk_full
bandwidth_probe_pending   ← evaluated before queue check
queue_empty
null
```

`bandwidth_probe_pending` fires before `queue_empty`, so an empty
queue with no probe yet → "probe pending" wins.

**Operator mental model:** "the scheduler shouldn't depend on the
probe; the probe only runs when there's work to do; if there's no
work, the scheduler is idle for the simple reason that the queue
is empty." The wait_reason should reflect that.

**Requested behaviour:**

1. **Reorder** so `queue_empty` is checked before
   `bandwidth_probe_pending`. With an empty queue → wait_reason
   `queue_empty`, regardless of probe state.
2. **Confirm** that the probe itself is gated on queue non-empty
   (i.e., it doesn't actually start when there's nothing to
   schedule). Operator's reading suggests it doesn't run, which
   makes "probe_pending" doubly wrong on an empty queue. If it
   *does* still run (e.g., on a periodic timer), please document
   that — but the wait_reason should still default to
   `queue_empty` when the queue has nothing in it.

No FE change required. The dashboard renders whatever
`state.wait_reason` says; once the priority is corrected, the
"idle · queue empty" read will appear without further work.

</details>

<details>
<summary>BG-46 (resolved) — original frontend brief retained for context</summary>

### BG-46: Expose `installed_via` on `lifecycle.aria2.result`

**Paired frontend gap:** FE-36 (chip already wired; just needs data)

The FE lifecycle row for aria2 now renders both `Managed by` and
`Installed via` chips, mirroring the dashboard's own row. Today the
backend populates `managed_by` (typically `launchd` on macOS) but
not `installed_via`, so the new chip stays hidden — even when aria2
was clearly installed via Homebrew.

**Why operators care:** `managed_by` and `installed_via` are
separate axes. "Managed by launchd" answers *who supervises the
process*; "Installed via brew" answers *which channel will deliver
upgrades*. Operators reading just `Managed by launchd` ask
"shouldn't this say brew?" — that's the confusion this solves.

**Detection (already proven):** The same heuristics that BG-43
applied to ariaflow-server work for aria2 — check whether the
binary path resolves under a Homebrew prefix (`/opt/homebrew/...`,
`/usr/local/Cellar/...`, `brew --prefix`-rooted path), under
`pipx`'s venv layout, under a global `npm` prefix, or none of those
(→ `source`/`null`).

**Shape:** Add `installed_via?: 'homebrew'|'pipx'|'npm'|'source'|null`
to `lifecycle.aria2.result`. No FE changes required when it lands —
the chip is already conditional on the field's presence.

**Also requested — Upgrade action for aria2:** A
`POST /api/lifecycle/aria2/update` endpoint that dispatches
`brew upgrade aria2` (homebrew) / `pipx upgrade …` / `npm i -g …`
mirroring BG-43's behaviour for ariaflow-server. Once the backend
declares this action in `lifecycle.aria2.actions`, the FE row will
render the button automatically (it iterates `row.actions`). The
operator question driving this: "why does ariaflow-server have an
Update button but aria2 doesn't?" — same answer should hold for
both.

</details>

<details>
<summary>BG-45 (resolved) — original frontend brief retained for context</summary>

### BG-45: Persist auto-start and auto-update as declaration preferences

**Paired frontend gap:** FE-35 (toggle controls in Options tab,
will be wired when backend ships the prefs)

Today auto-start and auto-update are action-driven only:

- aria2 auto-start is a one-shot Load/Unload click on the
  System Health row (BG-44 phase 2). After a reboot or
  reinstall, the operator has to click again.
- Updates are a manual `POST /api/lifecycle/.../update` (BG-43)
  per component. There's no scheduled check.

The operator should be able to declare the desired state once,
have it survive across restarts, and let a reconciliation loop
keep reality in sync. Concretely, two new preferences in the
declaration:

```ts
auto_start_aria2: boolean        // default: true on macOS/Linux, false otherwise
auto_update: boolean             // default: false (operator opts in)
auto_update_check_hours: number  // default: 24
```

**Reconciliation behavior** (backend):
- On `cmdServe` startup, after loading the declaration, reconcile
  aria2 supervisor plist to match `auto_start_aria2`. If `true`
  and plist absent → install; if `false` and plist present →
  uninstall.
- If `auto_update=true`, schedule a check every
  `auto_update_check_hours` hours: query the package manager
  for an available newer version and, if found, dispatch the
  same `update` action used by the manual button. Apply to
  ariaflow-server itself, ariaflow-dashboard (via the dashboard's
  /api/web/lifecycle endpoint), and aria2.
- Action-log entries (`auto_start_reconciled`, `auto_update_check`,
  `auto_update_applied`) so the operator can see what fired.

**Wire shape**:
- Read via `/api/declaration` (already in the FE preference flow).
- Surface current reconciliation state via `/api/lifecycle.aria2.
  result.auto_start.expected` (matches `installed` when reconciled
  successfully, mismatches surface as a warn chip on the FE).

**FE side** (will land in FE-35 once backend ships):
- Two toggles in Options tab → Scheduler section (or a new
  "Self-management" section): "Keep aria2 auto-start installed"
  and "Auto-update (every N hours)".
- Tied to `setPref('auto_start_aria2', …)` / `setPref('auto_update', …)`.
- The Load/Unload buttons on the aria2 row stay as
  "force-reconcile-now" affordances even when auto_start is on.

This is a meaningful piece of work — reconciliation is a new
loop, scheduled update checks are new infra, and the
package-manager "is there a newer version" check has its own
detection per installer (`brew outdated`, `pipx list --outdated`,
`npm outdated -g`). Worth phasing.

</details>

## Explicit non-requests (do not implement)

| Topic | Decision | Reason |
|-------|----------|--------|
| Per-interface RX/TX byte counters | **Do not add** | Ariaflow is a download manager, not a network monitor. |
| Interface enumeration via API | **Do not add** | Exposes network topology. Frontend already has `local_identity()`. |

## Resolved

| ID | Summary | Date |
|----|---------|------|
| BG-56 | Folder ops within `<download_dir>` shipped via new `packages/api/src/routes/files.ts`. Five endpoints — `GET /api/files` (single-level by default; `?recursive=true` capped at depth 3; joins each entry against the queue history via `output_path` for `history_match`), `POST /api/files/rename` ({path,new_name}; new_name must be a bare filename), `POST /api/files/move` ({path,new_subdir}), `DELETE /api/files` ({path,recursive?}; non-empty dir without `recursive: true` → 409), `POST /api/files/clean` ({status?,older_than_days?,orphaned?}; `orphaned: true` is reconcile-only, no disk side-effect). Path safety: `resolveSafe` realpath-canonicalizes the target (or its parent for non-existing destinations) and rejects anything that resolves outside the realpath of `<download_dir>`, plus a sep-aware `..`-traversal check before realpath to defeat symlink-creation races. After every mutation, queue rows whose `output_path` matches the source are updated (rename/move) or flagged `file_present_on_disk: false` (delete). Action-log entries use new `ACTIONS.file{Rename,Move,Delete,Clean}` + `TARGETS.files`. New optional `file_present_on_disk` field on `QueueItemRecord` | 2026-05-06 |
| BG-55 | Tier 1 verify-then-confirm landed (Tier 2/3 deferred — file infra in place when wanted). Phase 1: `output_path` + optional `remote_etag`/`remote_last_modified` fields on `QueueItemRecord`; `scheduler/poll.ts` captures `output_path` from `tellStatus(gid).files[0].path` on completion. Phase 2: new `awaiting_confirmation` status added to `ITEM_STATUSES` + `ALLOWED_ACTIONS` (confirm/skip/rename/remove). New declaration prefs `verify_existing_strategy` (default `local_only`, options off/local_only/local_and_remote_head/local_and_sampled_hash) and `confirm_redownload_default_action` (default `prompt`, options prompt/skip/rename/redownload). `QueueOps.add` runs `verifyExistingTier1` (stat `<download_dir>/<basename(url) or output>`); on hit, applies the default action — `prompt` → status `awaiting_confirmation`, `skip` → `removed`+`duplicate_skipped`, `rename` → `queued` (BG-54 auto-rename), `redownload` → `queued` with `allow_overwrite` flag. `dispatch.ts` honors per-item `allow_overwrite` (defaults remain BG-54 safe). Three new endpoints `POST /api/downloads/:id/{confirm,skip,rename}` flip status + log `confirm_redownload:<decision>`; confirm/rename auto-kick the scheduler when drained. Tier 2 (HEAD probe) and Tier 3 (sampled hash) not implemented — strategy field accepts those values but currently behaves as Tier 1 | 2026-05-06 |
| BG-54 | Dropped hardcoded `"allow-overwrite": "true"` from `baseOptions` in `packages/core/src/aria2/dispatch.ts`. aria2 now falls back to its default (`allow-overwrite: false` + `auto-file-renaming: true`), so re-adding a completed URL produces `<name>.1` instead of silently clobbering the existing file. `continue: true` still resumes partials via the `.aria2` control file regardless of overwrite setting. Test assertion updated in `dispatch.test.ts` | 2026-05-06 |
| BG-53 | Per-download `max-download-limit` is now refreshed alongside the global cap on every probe. After `setMaxOverallDownloadLimit`, both `routes/bandwidth.ts` (manual `POST /api/bandwidth/probe`) and the BG-52 periodic timer in `_scheduler_controller.ts` walk `tellActive(["gid"])` and call `setMaxDownloadLimit(client, gid, cap)` for each in-flight transfer. Per-gid failures are swallowed individually so one bad gid doesn't block the rest; if `tellActive` itself fails, the global cap is still applied | 2026-05-06 |
| BG-52 | Periodic bandwidth probe wired in `_scheduler_controller.ts`. After the loop launches, a `setInterval` re-runs `runBandwidthProbe` every `bandwidth_probe_interval_seconds` while `state.running && !state.paused && state.active_gid` (re-reading the declaration each tick so live changes apply). Each run updates `state.last_bandwidth_probe`/`last_bandwidth_probe_at`, applies the new cap to aria2 via `setMaxOverallDownloadLimit`/`setMaxOverallUploadLimit` (in-flight transfers adapt live), and records an action-log entry with `reason: "scheduler_periodic"`. Timer is `unref`'d, cleared on stop/crash/normal exit; interval≤0 disables | 2026-05-06 |
| BG-50 | `deriveSchedulerStatus` (`packages/core/src/scheduler/status.ts`) reordered: persistent `paused` flag now wins over the `!running` short-circuit, so a drained-but-paused loop (intent=running, running=false, paused=true, session open) reports `'paused'` instead of `'idle'`. The `intent=stopped` short-circuit still wins first (a paused state without operator-running-intent stays `'stopped'`). One new test in `status.test.ts` covers the BG-50 case; existing `running`/`idle`/`starting`/`stopped` tests untouched and still pass | 2026-05-06 |
| BG-49 | All four scheduler action routes (`/api/scheduler/{start,stop,pause,resume}`) now return a canonical `state: { scheduler_status, running, dispatch_paused, session_id, _rev }` envelope alongside their existing flat fields. New `buildStateEnvelope(deps, state)` helper in `routes/scheduler.ts` reuses `computeSchedulerStatus` so the `scheduler_status` value matches what `GET /api/status` would return immediately after. Existing flat `started/stopped/paused/_rev` fields stay for back-compat. Note: `scheduler_status` reflects current state — when scheduler intent is "stopped", a /pause flips `dispatch_paused` but keeps `scheduler_status:"stopped"` (intent unchanged); test assertions match that semantic. 4 new tests in BG-49 describe block | 2026-05-06 |
| BG-48 | New `POST /api/scheduler/contract` endpoint registered alongside `/api/scheduler/ucc`; both delegate to the same handler. Action-log token flipped from `"ucc"` to `"contract"` for both routes — `ACTIONS.schedulerUcc` kept as a deprecated alias of `ACTIONS.schedulerContract` so existing `ACTIONS.X` callers don't have to update in lock-step (both resolve to `"contract"`). `meta.contract` field shape unchanged (`{contract: "UCC", version: "2.0"}`); the FE doesn't need that value renamed (per BG-48 brief — only the wire-name was the concern). One test renamed to assert `action: "contract"`; one new test covers the `/contract` route shape | 2026-05-05 |
| BG-47 | `deriveWaitReason()` reordered: `queue_empty` is now checked before `bandwidth_probe_pending`, so an empty queue with no probe yet correctly reads `idle · queue empty` instead of "probe pending". Hard blockers (`aria2_unreachable` / `preflight_blocked` / `disk_full`) still win first. The probe itself isn't gated on queue contents — it runs once at scheduler-loop startup as a preloop step (`packages/cli/src/commands/_scheduler_controller.ts`); that's fine because the wait_reason now correctly defaults to `queue_empty` when there's nothing to schedule. One probe-pending test split into two so the assertion isolates the probe path with a pending item; one new test covers the BG-47 reorder explicitly | 2026-05-05 |
| BG-46 | `installed_via` now exposed on `lifecycle.aria2.result`, detected from the resolved `aria2c` path via the new `detectBinaryInstalledVia(binPath)` helper (shared logic with `detectAriaflowInstalledVia`, "source" verdict suppressed for third-party binaries). New action `POST /api/lifecycle/aria2/update` mirrors the ariaflow-server update flow: `brew upgrade aria2` (homebrew) / 409 with explanatory error for pipx/npm (aria2 isn't distributed via those) / 409 unknown_installer when path doesn't match. Detached subprocess + post-`reply.raw.finish` side-effect pattern reused from BG-43 | 2026-05-05 |
| BG-45 | Three new declaration preferences (`auto_start_aria2` defaulting true on macOS/Linux, `auto_update`, `auto_update_check_hours`) persisted via the existing PATCH /api/declaration/preferences. cmdServe now reconciles aria2's launchd plist / systemd unit on boot to match `auto_start_aria2` (install if true+missing, uninstall if false+present), logging `auto_start_reconciled`. A periodic auto-update controller polls every `auto_update_check_hours` when `auto_update` is on, runs `brew outdated --json=v2 ariaflow-server` (homebrew-only in v1; pipx/npm/source skip), and on a hit dispatches `brew upgrade ariaflow-server` detached. Both phases log `auto_update_check` (always) and `auto_update_applied` (on hit). New `aria2AutoStartInstalled()` helper in core; new `skipAutoStartReconcile` cmdServe flag so test harnesses don't mutate real launchd state | 2026-05-05 |
| BG-44 | Phase 3 (backend retires the standalone row). `data['aria2-launchd']` dropped from `/api/lifecycle`; auto-start info lives entirely on `aria2.result.auto_start` (shipped in phase 1). Action targets `aria2-launchd` / `aria2-systemd` / `aria2-service` for `{install,uninstall}` kept alive for back-compat (no rename). `buildAria2LaunchdRow` and the unused `detectServiceTarget` import removed. Tests updated to assert `body['aria2-launchd']` is undefined and that `auto_start` shape stays correct | 2026-05-05 |
| BG-43 | Two new axes on `/api/lifecycle.ariaflow-server.result`: `managed_by` (launchd/systemd/docker/external/null) and `installed_via` (homebrew/pipx/npm/source/null), auto-detected from `/.dockerenv`, `~/Library/LaunchAgents/*.plist`, `INVOCATION_ID`, ppid, `process.argv[1]` path, etc. (see `packages/core/src/install/ariaflow_self.ts`). Two new lifecycle actions: `POST /api/lifecycle/ariaflow-server/restart` dispatches `launchctl kickstart -k gui/UID/<label>` (launchd) / `systemctl --user restart ariaflow-server` (systemd) / `process.exit(0)` (docker) / 409 (external/null). `POST /api/lifecycle/ariaflow-server/update` dispatches `brew upgrade ariaflow-server` (homebrew) / `pipx upgrade ariaflow-server` (pipx) / `npm install -g @ariaflow/cli@latest` (npm) / 409 (source/null). Subprocesses spawned detached + unref()'d so the response isn't blocked; side effects fire on `reply.raw.on('finish')` after the 202 ack flushes. 7 new pure-helper tests for installed_via detection. Verified live on v0.1.273: `managed_by="launchd"`, `installed_via="homebrew"` | 2026-05-05 |
| BG-41 | Scheduler stuck in `starting` indefinitely after restart. Resolved as part of the wire-shape sweep — `afbcf93` (toWireState picks declared fields explicitly) plus the scheduler-controller fix verified live: state.running flips to true shortly after intent='running', heartbeat advances. FE workaround (Stop visible during 'starting') stays as defense in depth | 2026-05-05 |
| BG-42 | (1) `GET /favicon.ico` registered in `routes/meta.ts` returning 204 — silences the per-browser-session 404 that was inflating `health.errors_total`. (2) `health.errors_recent` ring buffer added to `ServerMetrics` (`routes/_context.ts`); `onResponse` hook in `server.ts` pushes `{at, method, path, status}` for every 4xx/5xx, capped at `ERRORS_RECENT_MAX=20` (older entries roll off). Surfaced on `/api/status.health.errors_recent`. `path` prefers Fastify's matched `routerPath` ("/api/downloads/:id") and falls back to raw `req.url` when not yet matched | 2026-05-05 |
| BG-40 | Richer scheduler status enum + wait_reason. New `state.scheduler_intent` (`"stopped"\|"running"`) is stamped by `/api/scheduler/{start,stop,resume}` and lets `deriveSchedulerStatus(state)` (in `packages/core/src/scheduler/status.ts`) return the 5-state enum: `stopped\|starting\|idle\|running\|paused`. `deriveWaitReason()` classifies idle reasons in priority order: `aria2_unreachable\|preflight_blocked\|disk_full\|bandwidth_probe_pending\|queue_empty\|null`. `GET /api/scheduler` now returns `{status, wait_reason, running, paused, ...}`; `/api/status.state` mirrors `scheduler_status` + `wait_reason` so the dashboard's System Health card avoids a second fetch. 13 pure-helper tests in `status.test.ts` cover every truth-table branch; server tests assert the new shape | 2026-05-05 |
| BG-39 | `/api/sessions/history` registered in the freshness contract (`swr`, ttl 30s) and the handler stamps via `withMeta`, matching `/api/sessions`. FE can drop the synthetic `LOCAL_METAS` mirror | 2026-05-05 |
| BG-38 | `/api/torrents` now returns `{ok: true, torrents, count, meta}`, aligning with `/api/peers` / `/api/sessions` and the `TestEnvelopeNormalization` live-contract tests | 2026-05-05 |
| BG-37 | `GET /api/openapi.yaml` now rewrites `info.version` at serve time to the runtime value (`deps.version`, sourced via BG-23 from cli/package.json), so the published contract artifact matches `/api/version`. Implementation in `packages/api/src/server.ts` uses an anchored regex on the `info:` block (single-line replace, leaves the rest of the spec byte-identical). Test in `server.test.ts` writes a stub yaml with `version: 0.1.145`, builds the server with version `0.1.244`, and asserts the served body contains `version: 0.1.244` and that `/api/version` reports the same value | 2026-05-04 |
| BG-34 | Per-tab loader endpoints registered in `/api/_meta` via `withMeta`. `packages/api/src/freshness.ts` adds: `GET /api/torrents` (warm 30s), `GET /api/peers` (warm 30s), `GET /api/downloads/archive` (swr 60s), `GET /api/sessions` (swr 30s), `GET /api/declaration` (cold; `revalidate_on` references the four POST/PUT/PATCH declaration mutators). All five handlers in `server.ts` now stamp meta via `withMeta`. BG-31 `_meta` route-reference test covers the new triggers | 2026-04-30 |
| BG-33 | Legacy field aliases dropped from `/api/status`. `state.paused` removed from payload (kept as internal storage field only); `summary.stopped` mirror removed; `"stopped"` removed from `ITEM_STATUSES` and `TERMINAL_STATUSES` (in both `packages/core/src/queue/types.ts` and `packages/core/src/state/archivable.ts`). Canonical names are `dispatch_paused` (top-level + on `state`) and `removed`. Three negative-snapshot tests in `server.test.ts` assert no occurrence of `state.paused`, `summary.stopped`, or `status:"stopped"` in `/api/status` responses. Out-of-scope `"stopped"` strings (scheduler-loop reason, torrent `distribute_status`) intentionally left — they belong to other domains. `docs/STATE_MACHINE.md` updated | 2026-04-30 |
| BG-32 | Per-topic SSE subscriptions (v1: connect-time filter only). `GET /api/events?topics=items,scheduler` filters the stream; missing/empty → all topics (back-compat); unknown names → empty subset (typo ≠ firehose). `packages/api/src/event-topics.ts` is the single source for the 5 topics (items/scheduler/log/lifecycle/bandwidth) and the event→topic map (action_logged→log, session_*→scheduler, state_changed→items+scheduler, lifecycle_changed→lifecycle, bandwidth_probed→bandwidth); unknown event names fall through to all topics so a new emitter is visible until classified. `FreshnessMeta` extended with `transport_topics`; `/api/status` declares `["items","scheduler"]`, surfaces verbatim in `/api/_meta`. Mid-stream subscribe/unsubscribe deferred (reconnect with different `?topics=` is the v1 path). `packages/api/src/sse.md` documents the vocabulary | 2026-04-30 |
| BG-31 | Per-endpoint freshness contract. `packages/api/src/freshness.ts` is the single registry; `withMeta(method, path, body)` stamps the registered block and throws on unregistered keys. Initial coverage: `/api/status` (live, sse), `/api/lifecycle` (warm 30s, revalidate on `POST /api/lifecycle/:target/:action`), `/api/bandwidth` (on-action, revalidate on `POST /api/bandwidth/probe`), `/api/aria2/get_global_option` + `/api/aria2/global_option` (cold), `/api/log` (swr 10s), `/api/health`, `/api/version`, `/api/_meta` (all bootstrap). New `GET /api/_meta` returns the registry sorted by path. Validators: warm/swr require `ttl_s`, on-action requires `revalidate_on`, live requires `transport`; server test confirms `revalidate_on` triggers reference routes Fastify actually registered. `docs/FRESHNESS.md` mirrors the dashboard's design rationale | 2026-04-30 |
| BG-30 | Download state machine aligned on aria2's vocabulary. (1) `pollActiveItems` now persists `item.status="waiting"` (was only `live_status`). (2) `removed` added to `ITEM_STATUSES`/`TERMINAL_STATUSES`; poll emits canonical `removed` (was `stopped`); `/api/status.summary` mirrors `removed`/`stopped` as aliases. (3) `cancelled` removed from types/policy/`ITEM_STATUSES` — unreachable. (4) `/api/status` dual-keys `dispatch_paused` (top-level + on `state`) alongside legacy `state.paused`. (5) `state.active_gid`/`active_url` derived from `aria2.tellActive()` at `/api/status` read time, with stamped state as fallback when daemon unreachable. (6) `docs/STATE_MACHINE.md` documents the 8 states + transitions | 2026-04-30 |
| BG-29 | `/api/lifecycle` adds `expected_running` and `managed_by` (each `bool\|null` / enum-or-null) to every component's `result`. aria2: `expected_running = state.running \|\| state.active_gid \|\| any item in {queued,waiting,active}`; `managed_by` = `"launchd"` when the launchd plist exists on disk and aria2 is reachable, else `"external"` (or `null` when not running). ariaflow-server / networkquality / aria2-launchd carry `null` for both axes (informational rows) | 2026-04-30 |
| BG-28 | (a) `runSchedulerTick` stamps `state.active_gid`/`active_url` with the most recently dispatched item; `pollActiveItems` keeps state pointed at the live active row and clears both fields when nothing's in flight. (b) Poll mirrors aria2's camelCase tellStatus keys (`downloadSpeed`, `uploadSpeed`, `completedLength`, `totalLength`, `connections`, `numSeeders`) onto each row and now marks the row dirty so progress refreshes actually persist | 2026-04-30 |
| BG-27 | `/api/lifecycle` adds three orthogonal axes per component (`installed` / `current` / `running`, each `bool \| null`) alongside the BG-20 reason/outcome/message fields; `aria2.installed` from `findAria2c()`, `aria2.running` from RPC reachability; `aria2-launchd` keeps installed/current null and proxies running through aria2 RPC; `networkquality.current` is null (no version policy), running derived from a recent successful probe; `ariaflow-server.expected_version` added | 2026-04-30 |
| BG-26 | `/api/status.bandwidth` actually lifted now (full `state.last_bandwidth_probe` spread + `last_probe_at`); BG-25's earlier resolution shipped the code but the deploy was stale — verified live in tests | 2026-04-30 |
| BG-25 | Canonical `running` semantic = "scheduler loop is actively dispatching"; `POST /api/scheduler/{start,stop}` added, `/resume` auto-starts the loop when `running:false`, `state.running` flipped by `runSchedulerLoop` only; `/api/status` lifts a top-level `bandwidth` summary from `state.last_bandwidth_probe` so the dashboard Cap chip works without visiting the Bandwidth tab | 2026-04-30 |
| BG-24 | `/api/status.health` populated (uptime, requests/errors/bytes counters via Fastify hooks, sse_clients via /api/events subscribe/unsubscribe, disk_ok via statfsSync + checkDiskSpace); `/api/log` returns `{ok: true, items}` for envelope consistency | 2026-04-30 |
| BG-23 | cmdServe auto-resolves version from cli/package.json → pyproject.toml → __init__.py (skipping the 0.0.0 placeholder); /api/{status,lifecycle,version} now report the real release | 2026-04-30 |
| BG-22 | `/api/aria2/{get_global_option,global_option,get_option,option}` spread the aria2 keys at top level instead of wrapping under `options` | 2026-04-30 |
| BG-21 | `/api/bandwidth` lifts `interface_name`, `source`, `cap_mbps`, `current_limit` to top level (legacy `interface`/`cap_bytes_per_sec` kept as aliases) | 2026-04-30 |
| BG-20 | `/api/lifecycle` reshape: hyphen keys, `result` wrapper, aria2 + aria2-launchd records, recognized `reason` enum | 2026-04-30 |
| BG-19 | `/api/status` populates `ariaflow-server: {reachable, pid, version, error}` | 2026-04-30 |
| BG-18 | Backend announces `_ariaflow-server._tcp` via mDNS at startup (--no-mdns to disable) | 2026-04-30 |
| BG-17 | AGENTS.md gap-governance section documents file structure + cross-repo boundary | 2026-04-30 |
| BG-16 | `ariaflow-web` -> `ariaflow-dashboard` rename verified in AGENTS.md / README.md / AGENT.md / docs/GAPS.md | 2026-04-30 |
| BG-15 | TS port `discovery/parse.ts` already uses `_ariaflow-server._tcp` literally; legacy Python `discovery.py` not in TS ship path | 2026-04-30 |
| BG-14 | `archivable_count` exposed on `/api/status` summary | 2026-04-09 |
| BG-13 | WSL detection + default download dir to Windows filesystem | 2026-04-09 |
| BG-12 | Removed unused `/api/sessions/new` endpoint | 2026-04-09 |
| BG-11 | Residual under-specified fields after BG-10 (frontend updated schemas) | 2026-04-08 |
| BG-1–10 | See git history | — |

Details for all resolved entries are preserved in git history.
