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

## Open (0)

_End of open gaps._

## Explicit non-requests (do not implement)

| Topic | Decision | Reason |
|-------|----------|--------|
| Per-interface RX/TX byte counters | **Do not add** | Ariaflow is a download manager, not a network monitor. |
| Interface enumeration via API | **Do not add** | Exposes network topology. Frontend already has `local_identity()`. |

## Resolved

| ID | Summary | Date |
|----|---------|------|
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
