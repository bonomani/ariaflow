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

### BG-31: Per-endpoint freshness contract + `/api/_meta` index

**Problem.** Every JSON endpoint today has the same effective refresh
strategy on the client (SSE tick → refetch everything). Hot data
(item progress) and cold data (lifecycle versions, options) ride the
same channel at the same rate. The client has to guess cadence per
endpoint; new mutations don't surface to the client. Design rationale,
prior-art comparison, and seven-class taxonomy in
`ariaflow-dashboard/docs/FRESHNESS_AXIS.md`.

**Required backend changes:**

1. **Add a `meta` block to every JSON endpoint:**
   ```json
   "meta": {
     "freshness": "bootstrap" | "live" | "warm" | "cold" | "on-action" | "swr" | "derived",
     "ttl_s": 30,
     "revalidate_on": ["POST /api/lifecycle/install"],
     "transport": "sse"
   }
   ```
   `ttl_s` required for `warm` / `swr`. `revalidate_on` required for `on-action`. `transport` required for `live`.

2. **Single server-side registry.** One helper (e.g. `withMeta(endpointKey, body)`) reads from a per-endpoint registration so the same source feeds both inline `meta` blocks and the index. No two declarations of the same fact.

3. **`GET /api/_meta`** — returns
   ```json
   { "endpoints": [{ "method": "GET", "path": "/api/lifecycle", "freshness": "warm", "ttl_s": 30, "revalidate_on": ["POST /api/lifecycle/install","POST /api/lifecycle/uninstall"] }, ...] }
   ```
   Itself classified `bootstrap` (cached for the session). Generated from the registry — never hand-maintained.

4. **Initial coverage targets** (where the first wins live):
   - `/api/status` → `live` (SSE-pushed)
   - `/api/lifecycle` → `warm`, `ttl_s: 30`, `revalidate_on: ["POST /api/lifecycle/install","POST /api/lifecycle/uninstall"]`
   - `/api/bandwidth` → `on-action`, `revalidate_on: ["POST /api/bandwidth/probe"]`
   - `/api/options` → `cold`
   - `/api/log` → `swr`, `ttl_s: 10`
   - `/api/health`, `/api/version` → `bootstrap`

5. **Test-time validators:**
   - Every route handler must be registered (no implicit endpoints in `_meta`).
   - `bootstrap` endpoints return byte-identical bodies across calls in tests.
   - `live` endpoints declare a `transport`.
   - `on-action` endpoints' `revalidate_on` references existing routes.

6. **Document the vocabulary** in `ariaflow-server/docs/FRESHNESS.md` (server-side mirror) so the contract is co-located with the code that emits it. Reference `ariaflow-dashboard/docs/FRESHNESS_AXIS.md` as the design rationale.

**Frontend code refs (paired update FE-24, blocked by this):**
- `ariaflow-dashboard/src/ariaflow_dashboard/static/ts/` — new `FreshnessRouter` module
- `ariaflow-dashboard/src/ariaflow_dashboard/static/ts/app.ts` — replace eager SSE-tick refetch
- `ariaflow-dashboard/src/ariaflow_dashboard/static/_fragments/tab_dev.html` — Freshness map panel
- `ariaflow-dashboard/package.json` — `npm run freshness:snapshot` script

**Sequence:** backend lands #1–6 with initial coverage (#4) → frontend ships `FreshnessRouter` + Dev panel (FE-24) → expand backend coverage to remaining endpoints.

**Priority:** medium — current behavior works but wastes bandwidth/battery on hidden tabs and on cold endpoints, and there's no observability on which endpoint the dashboard is hammering.

**Anti-goals:** not a cache implementation, not a transport, not enforcement (server lying about class is a bug, not a security issue). Schema is advisory.



## Explicit non-requests (do not implement)

| Topic | Decision | Reason |
|-------|----------|--------|
| Per-interface RX/TX byte counters | **Do not add** | Ariaflow is a download manager, not a network monitor. |
| Interface enumeration via API | **Do not add** | Exposes network topology. Frontend already has `local_identity()`. |

## Resolved

| ID | Summary | Date |
|----|---------|------|
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
