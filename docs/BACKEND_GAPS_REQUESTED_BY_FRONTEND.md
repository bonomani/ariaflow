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

### BG-30: Align download state machine on aria2's vocabulary

**Problem.** Three layers use three different vocabularies for the same
states. aria2 reports `active`/`waiting`/`paused`/`error`/`complete`/`removed`.
Backend renames some, drops others, and invents an unreachable one
(`cancelled`). Frontend invents aliases (`done`/`downloading`/`failed`/`recovered`).
The word `paused` is overloaded across scheduler-level (`state.paused`,
halts dispatch) and item-level (`item.status="paused"`, single download).
`waiting` is reported by aria2, cached in `item.live_status`, but never
persisted as `item.status` or counted in `summarizeQueue`.

**Target canonical states:**
- aria2-native (persisted as-is): `active`, `waiting`, `paused`, `error`, `complete`, `removed`
- backend-only (pre-aria2 staging): `discovering`, `queued`

Diagram: `discovering → queued → (active ⇄ waiting ⇄ paused) → {complete, error, removed}`

**Required backend changes (ship dual-keyed for one release where noted):**

1. **Persist `waiting`.** In `pollActiveItems`, when aria2's `live_status="waiting"`, call `transitionStatus(item, "waiting")`. Add `waiting` to `summarizeQueue` buckets so `summary.waiting` populates.
2. **Rename `stopped` → `removed`.** Match aria2. Emit `item.status: "removed"`; mirror `summary.removed` and keep `summary.stopped` as an alias counter for one release. Add `removed` to `ITEM_STATUSES`, remove `stopped` after frontend cutover.
3. **Delete `cancelled`** from `ITEM_STATUSES`, `policy.allowedActions`, types — unreachable, no producer.
4. **Disambiguate scheduler pause.** Rename the JSON field `state.paused` → `state.dispatch_paused` on `/api/status` (item-level `paused` keeps its name). Endpoints stay `/api/scheduler/{pause,resume}`. Dual-key `state.paused` for one release.
5. **`active_gid` derived from `aria2.tellActive()`.** Compute on `/api/status` read instead of stamping in `tick`/`poll`. Removes the stale-after-crash class. Same for `active_url`.
6. **Document the state machine** in `docs/STATE_MACHINE.md`: 8 states, all transitions, who triggers each (user API, scheduler, poller, aria2).

**Frontend code refs (paired update tracked as FE-23):**
- `ariaflow-dashboard/src/ariaflow_dashboard/static/ts/filters.ts` (`normalizeStatus`, bucket aliases)
- `ariaflow-dashboard/src/ariaflow_dashboard/static/ts/formatters.ts` (badge color map)
- `ariaflow-dashboard/src/ariaflow_dashboard/static/ts/app.ts` (`schedulerOverviewLabel`, summary reads, `state.paused` reads)

**Sequence:** backend ships #1–6 dual-keyed → frontend cuts over (FE-23) → backend drops aliases.

**Priority:** medium — current behavior works but accumulates phantom-state debt and confuses contributors.



## Explicit non-requests (do not implement)

| Topic | Decision | Reason |
|-------|----------|--------|
| Per-interface RX/TX byte counters | **Do not add** | Ariaflow is a download manager, not a network monitor. |
| Interface enumeration via API | **Do not add** | Exposes network topology. Frontend already has `local_identity()`. |

## Resolved

| ID | Summary | Date |
|----|---------|------|
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
