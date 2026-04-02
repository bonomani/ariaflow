# BISS Classification — Ariaflow

## Boundary Inventory

| Boundary | Type | Direction | Classification | Notes |
|---|---|---|---|---|
| aria2 RPC | tool-to-tool | outbound | execution | Scheduler → aria2 daemon via JSON-RPC |
| HTTP API (af-api) | system-to-user | inbound | query / command | External clients → scheduler REST API (/api/*) |
| SSE events | system-to-user | outbound | real-time state push | Server-Sent Events at /api/events |
| OpenAPI / Swagger | system-to-user | outbound | documentation | /api/docs and /api/openapi.yaml |
| Queue file | system-to-storage | internal | state persistence | JSON file read/write for queue state |
| Archive file | system-to-storage | internal | soft-delete persistence | archive.json for cancelled/old items |
| Session history | system-to-storage | internal | audit persistence | sessions.jsonl for session log |
| Declaration file | system-to-storage | internal | contract persistence | UCC declaration stored as JSON |
| Config directory | system-to-filesystem | internal | configuration | Scheduler config and state directory |
| Bonjour/mDNS | system-to-network | outbound | discovery | Service advertisement on local network |
| Homebrew | system-to-package-manager | external | installation | brew install/upgrade lifecycle |

## Interaction Classes

- **execution**: the af-scheduler delegates download work to aria2 via RPC
- **query/command**: external clients read state or issue commands via af-api
- **real-time push**: SSE stream pushes state_changed events to connected clients
- **documentation**: OpenAPI spec and Swagger UI for API discovery
- **state persistence**: queue, archive, and declaration files are the source of truth
- **audit persistence**: session history log for session lifecycle tracking
- **discovery**: Bonjour advertises the service for local network clients
- **installation**: Homebrew manages the install/upgrade lifecycle
