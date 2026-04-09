# ariaflow-server

Headless queue driver for `aria2c`.

**Targets:** Linux, WSL, macOS  
**Python:** >= 3.10, zero dependencies  
**Version:** 0.1.148

**Features:**

- URL enqueueing (HTTP, magnet, torrent, metalink, mirrors)
- Sequential execution by default, configurable concurrency
- Adaptive bandwidth control via networkQuality probing (macOS)
- Full aria2 1.37.0 RPC coverage (36 `aria2_*` wrapper functions)
- REST API (16 GET + 17 POST endpoints) with SSE real-time events
- Torrent/metalink file selection via pause-metadata flow
- UIC pre-flight gates, UCC structured execution output
- macOS integration (Homebrew, launchd, Bonjour/mDNS)

## Quick Start

```bash
pip install -e .
ariaflow-server serve              # start HTTP API on 127.0.0.1:8000
ariaflow-server add <url>          # enqueue a download
ariaflow-server run                # start the scheduler
ariaflow-server status             # show queue state
```

## CLI Commands

| Command | Description | Key flags |
|---|---|---|
| `ariaflow-server add <url>` | Enqueue a download | `--output`, `--priority`, `--mirror`, `--torrent-data`, `--metalink-data` |
| `ariaflow-server run` | Start the scheduler | `--port` (aria2 RPC port, default 6800) |
| `ariaflow-server serve` | Start HTTP API server | `--host` (default 127.0.0.1), `--port` (default 8000) |
| `ariaflow-server status` | Show queue and scheduler state | `--json` |
| `ariaflow-server preflight` | Run UIC pre-flight checks | `--json` |
| `ariaflow-server ucc` | Run structured UCC execution cycle | `--port`, `--json` |
| `ariaflow-server install` | Install on macOS | `--dry-run`, `--with-aria2` |
| `ariaflow-server uninstall` | Remove macOS components | `--dry-run`, `--with-aria2` |
| `ariaflow-server lifecycle` | Show install and service status | |

Also: `python -m aria_queue <command>`

## REST API

Base URL: `http://127.0.0.1:8000`

### GET endpoints

| Endpoint | Description |
|---|---|
| `/api/status` | Queue items, scheduler state, summary (2s cache) |
| `/api/scheduler` | Scheduler status |
| `/api/bandwidth` | Current bandwidth status and probe data |
| `/api/log?limit=120` | Action log |
| `/api/downloads/archive?limit=100` | Archived (removed/completed) items |
| `/api/sessions` | Session history |
| `/api/sessions/stats` | Session statistics |
| `/api/declaration` | UIC declaration (gates, preferences, policies) |
| `/api/aria2/get_global_option` | Current aria2 global options |
| `/api/aria2/get_option?gid=X` | Per-GID aria2 options |
| `/api/lifecycle` | Install and service status |
| `/api/downloads/{id}/files` | File list for torrent/metalink item |
| `/api/events` | SSE event stream (real-time state changes) |
| `/api/openapi.yaml` | OpenAPI specification |
| `/api/docs` | Swagger UI |
| `/api/tests` | Run test suite |

### POST endpoints

| Endpoint | Body | Description |
|---|---|---|
| `/api/downloads/add` | `{items: [{url, output?, priority?, mirrors?, torrent_data?, metalink_data?}]}` | Enqueue downloads |
| `/api/scheduler/start` + `/api/scheduler/stop` | `{action: "start"\|"stop"}` | Start/stop scheduler |
| `/api/scheduler/pause` | — | Pause all active transfers |
| `/api/scheduler/resume` | — | Resume all paused transfers |
| `/api/downloads/{id}/pause` | — | Pause single item |
| `/api/downloads/{id}/resume` | — | Resume single item |
| `/api/downloads/{id}/remove` | — | Remove item (archive) |
| `/api/downloads/{id}/retry` | — | Retry failed item |
| `/api/downloads/{id}/files` | `{select: [1,3,5]}` | Select torrent/metalink files |
| `/api/scheduler/preflight` | — | Run pre-flight checks |
| `/api/scheduler/ucc` | — | Execute UCC cycle |
| `/api/bandwidth/probe` | — | Trigger bandwidth probe |
| `/api/downloads/cleanup` | `{max_done_age_days?, max_done_count?}` | Clean up terminal items |
| `/api/declaration` | `{...declaration}` | Save UIC declaration |
| `/api/aria2/change_global_option` | `{options: {...}}` | Change aria2 global options (3-tier safety) |
| `/api/sessions/new` | `{close_reason?}` | Create new session |
| `/api/lifecycle/{target}/{action}` | `{action: ...}` | Install/service action |

## Design Goals

- Prefer finishing one download before starting the next
- Allow operators to raise concurrency via `max_simultaneous_downloads` preference
- Start with a conservative bandwidth cap derived from networkQuality probe
- Lower the cap when aria2 reports retries or errors
- Keep post-download handling policy-driven (`post_action_rule`)
- Emit structured UCC results for each run

## Storage

Default state files under `~/.config/aria-queue/` (override: `ARIA_QUEUE_DIR`):

| File | Purpose |
|---|---|
| `queue.json` | Download items with status, GID, timestamps |
| `state.json` | Scheduler state, session, bandwidth probe cache |
| `archive.json` | Soft-deleted items |
| `declaration.json` | UIC gates, preferences, policies |
| `actions.jsonl` | Audit log (auto-rotated at 512 KB) |
| `sessions.jsonl` | Session history |
| `aria2.log` | aria2 daemon log |
| `.storage.lock` | File lock for mutual exclusion |

## Documentation

All documentation lives in [`docs/`](./docs/):

| Document | Description |
|---|---|
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | Engine architecture, design principles, source structure |
| [STATES_AND_INTERACTIONS.md](./docs/STATES_AND_INTERACTIONS.md) | All states, transitions, and aria2 interaction model |
| [ARIA2_RPC_WRAPPERS.md](./docs/ARIA2_RPC_WRAPPERS.md) | Auto-generated reference of 36 `aria2_*` wrappers |
| [FRONTEND-GUIDE.md](./docs/FRONTEND-GUIDE.md) | Frontend integration: item fields, states, modes, API usage |
| [RELEASE.md](./docs/RELEASE.md) | Release process and tooling |
| [GAPS.md](./docs/GAPS.md) | Feature gap analysis |
| [governance/](./docs/governance/) | BGS, ASM, BISS, TIC governance framework |

## Homebrew (macOS)

```bash
brew tap bonomani/ariaflow-server
brew install ariaflow-web    # installs ariaflow-server + web frontend
brew services start ariaflow-server
brew services start ariaflow-web
```

- `ariaflow-server` — headless scheduler + REST API
- `ariaflow-web` — web frontend (separate repo, connects via `ARIAFLOW_API_URL`)

Tap formulas in `bonomani/homebrew-ariaflow-server` update automatically on each release.

## Release

See [`docs/RELEASE.md`](./docs/RELEASE.md).

```bash
python3 scripts/publish.py plan   # preview
python3 scripts/publish.py push   # push + auto-release
```

## License

**Proprietary.** Copyright (c) 2026 bonomani. All rights reserved.

Free to **use** for personal and internal business purposes. Modification, redistribution, and commercial resale are prohibited. See [LICENSE](./LICENSE).

This software communicates with [aria2](https://aria2.github.io/) (GPL-2.0) via JSON-RPC as a separate process. aria2 is not distributed with ariaflow-server — install it independently.

**AI policy:** Source code may NOT be used for AI training. Documentation IS freely referenceable. See [AI-USAGE.md](./AI-USAGE.md).

**Report a violation:** If you believe this license has been violated, contact the copyright holder via [GitHub Issues](https://github.com/bonomani/ariaflow-server/issues) or file a [DMCA takedown](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy) if the code has been redistributed.
