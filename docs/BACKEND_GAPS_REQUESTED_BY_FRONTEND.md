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

<!-- All current backend gaps are resolved. See the Resolved table below. -->

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
