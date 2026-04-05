# BISS Classification — Ariaflow

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
| Bonjour/mDNS | system-to-network | outbound | discovery | Service advertisement on local network |
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
| **installation** | Homebrew manages the install/upgrade lifecycle via tap formulas |
