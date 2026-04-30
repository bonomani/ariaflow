# ariaflow-server

Headless queue driver for `aria2c`.

**Targets:** Linux, WSL, macOS
**Runtime:** Node.js >= 20
**Distribution:** Homebrew tap + npm (`@ariaflow/cli`)

**Features:**

- URL enqueueing (HTTP, magnet, torrent, metalink, mirrors)
- Sequential execution by default, configurable concurrency
- Adaptive bandwidth control via networkQuality probing (macOS)
- Full aria2 1.37.0 RPC coverage
- REST API with SSE real-time events; per-endpoint freshness contract (`/api/_meta`)
- Torrent/metalink file selection via pause-metadata flow
- UIC pre-flight gates, UCC structured execution output
- macOS integration (Homebrew, launchd, Bonjour/mDNS)

## Quick Start

```bash
# Homebrew (recommended on macOS)
brew tap bonomani/ariaflow-server
brew install ariaflow-server

# or npm
npm install -g @ariaflow/cli

ariaflow serve              # start HTTP API on 127.0.0.1:8000
ariaflow add <url>          # enqueue a download
ariaflow run                # start the scheduler
ariaflow status             # show queue state
```

## CLI Commands

| Command | Description | Key flags |
|---|---|---|
| `ariaflow add <url>` | Enqueue a download | `--output`, `--priority`, `--mirror`, `--torrent-data`, `--metalink-data` |
| `ariaflow run` | Start the scheduler | `--port` (aria2 RPC port, default 6800) |
| `ariaflow serve` | Start HTTP API server | `--host` (default 127.0.0.1), `--port` (default 8000) |
| `ariaflow status` | Show queue and scheduler state | `--json` |
| `ariaflow preflight` | Run UIC pre-flight checks | `--json` |
| `ariaflow ucc` | Run structured UCC execution cycle | `--port`, `--json` |
| `ariaflow install` | Install on macOS | `--dry-run`, `--with-aria2` |
| `ariaflow uninstall` | Remove macOS components | `--dry-run`, `--with-aria2` |
| `ariaflow lifecycle` | Show install and service status | |

## REST API

Base URL: `http://127.0.0.1:8000`

Each JSON response carries a `meta` block declaring its freshness
class (`live`, `warm`, `cold`, `bootstrap`, `on-action`, `swr`,
`derived`). The full registry is at `GET /api/_meta`. See
[`docs/FRESHNESS.md`](./docs/FRESHNESS.md).

### GET endpoints

| Endpoint | Description |
|---|---|
| `/api/status` | Queue items, scheduler state, summary (live/SSE) |
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
| `/api/events?topics=...` | SSE event stream (per-topic filtering) |
| `/api/_meta` | Per-endpoint freshness contract |
| `/api/openapi.yaml` | OpenAPI specification |
| `/api/docs` | Swagger UI |

### POST endpoints

| Endpoint | Body | Description |
|---|---|---|
| `/api/downloads/add` | `{items: [{url, output?, priority?, mirrors?, torrent_data?, metalink_data?}]}` | Enqueue downloads |
| `/api/scheduler/{start,stop}` | — | Start/stop scheduler loop |
| `/api/scheduler/{pause,resume}` | — | Pause/resume dispatch |
| `/api/downloads/{id}/{pause,resume,remove,retry}` | — | Per-item actions |
| `/api/downloads/{id}/files` | `{select: [1,3,5]}` | Select torrent/metalink files |
| `/api/scheduler/preflight` | — | Run pre-flight checks |
| `/api/scheduler/ucc` | — | Execute UCC cycle |
| `/api/bandwidth/probe` | — | Trigger bandwidth probe |
| `/api/downloads/cleanup` | `{max_done_age_days?, max_done_count?}` | Clean up terminal items |
| `/api/declaration` | `{...declaration}` | Save UIC declaration |
| `/api/aria2/change_global_option` | `{options: {...}}` | Change aria2 global options (3-tier safety) |
| `/api/lifecycle/{target}/{action}` | — | Install/service action |

## Design Goals

- Prefer finishing one download before starting the next
- Allow operators to raise concurrency via `max_simultaneous_downloads` preference
- Start with a conservative bandwidth cap derived from networkQuality probe
- Lower the cap when aria2 reports retries or errors
- Keep post-download handling policy-driven (`post_action_rule`)
- Emit structured UCC results for each run

## Storage

Default state files under `~/.config/ariaflow-server/` (override: `ARIAFLOW_DIR`):

| File | Purpose |
|---|---|
| `queue.json` | Download items with status, GID, timestamps |
| `state.json` | Scheduler state, session, bandwidth probe cache |
| `archive.json` | Soft-deleted items |
| `declaration.json` | UIC gates, preferences, policies |
| `actions.jsonl` | Audit log (auto-rotated at 512 KB) |
| `sessions.jsonl` | Session history |
| `.storage.lock` | File lock for mutual exclusion |

## Workspace layout

| Package | Description |
|---|---|
| `packages/core` | Pure logic: storage, scheduler, aria2 client, contracts |
| `packages/api` | Fastify HTTP/SSE server (`@ariaflow/api`) |
| `packages/cli` | `ariaflow` CLI binary (`@ariaflow/cli`) |

```bash
corepack enable
pnpm install
pnpm build
pnpm test
```

## Documentation

| Document | Description |
|---|---|
| [docs/STATE_MACHINE.md](./docs/STATE_MACHINE.md) | Item states + transitions |
| [docs/FRESHNESS.md](./docs/FRESHNESS.md) | Per-endpoint freshness contract (`/api/_meta`) |
| [docs/RELEASE.md](./docs/RELEASE.md) | Release process |
| [docs/GAPS.md](./docs/GAPS.md) | Feature gap analysis |
| [docs/governance/](./docs/governance/) | BGS, ASM, BISS, TIC governance framework |
| [packages/api/src/sse.md](./packages/api/src/sse.md) | SSE topic vocabulary |

## Homebrew (macOS)

```bash
brew tap bonomani/ariaflow-server
brew install ariaflow-server
brew services start ariaflow-server
```

The tap is at `bonomani/homebrew-ariaflow-server`; the formula is
re-rendered and pushed automatically on each release tag (see
`.github/workflows/release-{formula,tap}.yml`).

The web dashboard is a separate repo: `ariaflow-dashboard`.

## Platform dependencies

| Dependency | macOS | Windows | Linux | WSL2 |
|---|---|---|---|---|
| Node.js ≥20 | `brew install node` | [nodejs.org](https://nodejs.org) or `winget install OpenJS.NodeJS` | distro pkg / nvm | distro pkg / nvm |
| aria2 | `brew install aria2` | [manual](https://aria2.github.io) | `apt install aria2` | `apt install aria2` |
| Bonjour/mDNS | built-in | [iTunes](https://support.apple.com/kb/DL999) or Bonjour SDK | `apt install avahi-daemon avahi-utils` | `dns-sd.exe` via interop |
| networkquality | built-in (macOS 12+) | n/a | n/a | n/a |

Bonjour is **optional** — peer discovery is disabled without it.

### WSL2 notes

- WSL2 is NATed by default — mDNS advertisements won't reach the host LAN
- Enable mirrored networking in `%USERPROFILE%\.wslconfig`:
  ```ini
  [wsl2]
  networkingMode=mirrored
  ```
- Config dir defaults to `~/.config/ariaflow-server/` (override `ARIAFLOW_DIR`)

## Release

See [`docs/RELEASE.md`](./docs/RELEASE.md). On every `v*` tag push:

1. `release-npm.yml` publishes `@ariaflow/{core,api,cli}` to npm.
2. `release-formula.yml` renders the Homebrew formula and attaches it to the GitHub release.
3. `release-tap.yml` mirrors the formula into the tap repo.

## License

**Proprietary.** Copyright (c) 2026 bonomani. All rights reserved.

Free to **use** for personal and internal business purposes. Modification, redistribution, and commercial resale are prohibited. See [LICENSE](./LICENSE).

This software communicates with [aria2](https://aria2.github.io/) (GPL-2.0) via JSON-RPC as a separate process. aria2 is not distributed with ariaflow-server — install it independently.

**AI policy:** Source code may NOT be used for AI training. Documentation IS freely referenceable. See [AI-USAGE.md](./AI-USAGE.md).

**Report a violation:** If you believe this license has been violated, contact the copyright holder via [GitHub Issues](https://github.com/bonomani/ariaflow-server/issues) or file a [DMCA takedown](https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy) if the code has been redistributed.
