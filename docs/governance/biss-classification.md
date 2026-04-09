# BISS Classification — Ariaflow-server

## Boundary Inventory

| Boundary | Type | Direction | Classification | Notes |
|---|---|---|---|---|
| aria2 RPC | tool-to-tool | outbound | execution | Scheduler → aria2 daemon via JSON-RPC (36 `aria2_*` wrappers) |
| HTTP API (af-api) | system-to-user | inbound | query / command | External clients → scheduler REST API (`/api/*`) |
| SSE events | system-to-user | outbound | real-time state push | Server-Sent Events at `/api/events` |
| OpenAPI / Swagger | system-to-user | outbound | documentation | `/api/docs` and `/api/openapi.yaml` |
| Queue file | system-to-storage | internal | state persistence | `queue.json` — download items with status, GID, timestamps |
| State file | system-to-storage | internal | state persistence | `state.json` — scheduler state, session, bandwidth |
| Archive file | system-to-storage | internal | soft-delete persistence | `archive.json` — cancelled/old items |
| Action log | system-to-storage | internal | audit persistence | `actions.jsonl` — all operations (auto-rotated at 512 KB) |
| Session history | system-to-storage | internal | audit persistence | `sessions.jsonl` — session lifecycle log |
| Declaration file | system-to-storage | internal | contract persistence | `declaration.json` — UIC gates, preferences, policies |
| File lock | system-to-storage | internal | concurrency control | `.storage.lock` — fcntl + RLock mutual exclusion |
| Config directory | system-to-filesystem | internal | configuration | `~/.config/aria-queue/` (override via `ARIA_QUEUE_DIR`) |
| Bonjour/mDNS | system-to-network | outbound | discovery | `_ariaflow._tcp` service advertisement; torrent discovery via `GET /api/torrents` |
| Peer polling | system-to-peer | outbound | peer auto-download | `discovery.py` browses `_ariaflow._tcp`, polls peer `GET /api/torrents`, auto-fetches new torrents (gated by `auto_discover_peers`) |
| Internal tracker | system-to-network | outbound | distribution | Private BitTorrent tracker announce URL for torrent distribution |
| Torrent file serving | system-to-user | outbound | distribution | `GET /api/torrents/{infohash}.torrent` serves created `.torrent` files |
| BitTorrent swarm | system-to-network | bidirectional | distribution | aria2 seeds private torrents to peers on internal tracker |
| Homebrew | system-to-package-manager | external | installation | `brew install/upgrade` lifecycle |

## Interaction Classes

| Class | Description |
|---|---|
| **execution** | af-scheduler delegates download work to aria2 via JSON-RPC. All 36 aria2 methods have dedicated `aria2_*` wrapper functions in `core.py`. |
| **query/command** | External clients read state or issue commands via af-api (`/api/status`, `/api/downloads/add`, `/api/downloads/{id}/pause`, etc.) |
| **real-time push** | SSE stream at `/api/events` pushes `state_changed` events to connected clients |
| **documentation** | OpenAPI spec and Swagger UI for API discovery |
| **state persistence** | `queue.json`, `state.json`, `declaration.json` are the source of truth, accessed under file lock |
| **audit persistence** | `actions.jsonl` and `sessions.jsonl` provide full operational history |
| **discovery** | Bonjour advertises the service for local network clients |
| **peer auto-download** | `discovery.py` polls discovered peers and auto-fetches new torrents (`peer_discovered`, `peer_fetch`, `peer_removed` actions) |
| **distribution** | Private torrent creation, seeding, and file serving for internal content distribution |
| **installation** | Homebrew manages the install/upgrade lifecycle via tap formulas |

## Action Catalog

Every `record_action(action=...)` value is listed here with its target and BGS trace.

| Action | Target | Trace | Description |
|---|---|---|---|
| `add` | queue | ASM Job: → queued | New download enqueued |
| `pause` | queue_item / active_transfer | ASM Job: → paused | User pauses a download |
| `resume` | queue_item / active_transfer | ASM Job: paused → | User resumes a paused download |
| `remove` | queue_item / active_transfer | ASM Job: → cancelled | User removes a download |
| `retry` | queue_item | ASM Job: error → queued | User retries a failed download |
| `priority` | queue_item | Job ordering | User changes item priority |
| `select_files` | queue_item | UIC: file selection | Torrent/metalink file selection |
| `run` | queue_item | ASM Job: queued/paused → active | Recorded by scheduler.py when an item is submitted to aria2 (`reason=download_started`); Job-axis transition, not Run-axis |
| `stop` | queue | (deprecated) | Removed legacy scheduler stop event — kept here for historical action_log entries; scheduler now auto-runs |
| `complete` | queue_item | ASM Job: → complete | Download finished successfully |
| `error` | queue / queue_item | ASM Job: → error | Download failed or RPC failure |
| `auto_retry` | queue_item | ASM Job: error → queued | Automatic retry by scheduler |
| `poll` | queue_item | ASM Job: polled | Scheduler poll cycle on active download |
| `preflight` | system | UIC: gate evaluation | Preflight readiness check |
| `ucc` | queue | UCC: execution cycle | UCC structured execution |
| `probe` | bandwidth / system | UCC: observation | Bandwidth probe |
| `session` | system | ASM Session: → open | New session created |
| `cleanup` | queue | Reconcile | Startup cleanup of stale queue state |
| `reconcile` | queue | Reconcile | Live queue reconciliation with aria2 |
| `deduplicate` | queue | UIC: dedup policy | Duplicate active transfer cleanup |
| `auto_cleanup` | queue | Auto-archive | Old done items archived automatically |
| `change_options` | queue | UIC: 3-tier safety | aria2 global option change |
| `patch_preferences` | declaration | UIC: atomic patch | `PATCH /api/declaration/preferences` |
| `lifecycle_action` | system | Install/uninstall | macOS lifecycle event |
| `bonjour_register` | system | Discovery boundary | Bonjour service registration |
| `bonjour_deregister` | system | Discovery boundary | Bonjour service deregistration on shutdown |
| `seed_expired` | queue_item | Distribution: expiration | Seeded torrent reached time/count limit |
| `seed_stopped` | queue_item | Distribution | Seeded torrent manually stopped |
| `discovery_start` | system | Peer polling boundary | Peer discovery thread started |
| `discovery_stop` | system | Peer polling boundary | Peer discovery thread stopped |
| `peer_discovered` | system | Peer polling boundary | New peer appeared on the network |
| `peer_removed` | system | Peer polling boundary | Peer disappeared from the network |
| `peer_fetch` | queue_item | Peer polling boundary | Auto-downloaded a torrent from a discovered peer |
