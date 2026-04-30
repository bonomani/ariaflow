# Codebase Audit — ariaflow-server

Updated: 2026-04-30. Basis: 513 tests across 42 files, 3 packages
(`api`, `cli`, `core`), ~15.8k TS source lines (incl. tests).

The Python tree was retired in commit `88dd282`; this audit covers the
TypeScript port only. The catalog of in-flight findings now lives in
`docs/PLAN.md` (open work) and the per-domain gap files
(`docs/GAPS.md`, `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md`).

## Snapshot

| Phase | Status |
|---|---|
| Security | URL/path/ID validation, error masking, 3-tier option safety |
| Performance | aria2 `system.multicall` batching |
| API consistency | Standardized error envelope, RPC-aligned endpoints, `/api/_meta` freshness registry (BG-31) |
| Correctness | Storage lock, GID normalization, metalink fallback, path resolve, BG-30 state-machine alignment |
| Observability | `/api/health`, `/api/_meta`, per-topic SSE filter (BG-32) |
| Tests | 513 vitest cases; trace targets inline as `BG-N` / `ASM CR-N` comments on `it(...)` blocks |
| Documentation | OpenAPI generated from code, STATE_MACHINE.md current, FRESHNESS.md current |
| DevEx | pnpm workspace, single-formula Homebrew tap, ESLint + tsc CI |
| Features | Per-item action API, file selection (torrent/metalink), aria2 global option proxy with safety tiers, Docker image |

## Open follow-ups

See `docs/PLAN.md` for active work and `docs/GAPS.md` / `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md` for cross-cutting gaps. Recurring drift watchpoints:

- **Governance counts** (`BGS.md`, `bgs-decision.yaml`, `tic-oracle.md`) must be bumped in any commit that adds/removes tests — easy to forget.
- **Architecture/state docs still describe the Python module layout**: `docs/ARCHITECTURE.md` ("`core.py`/`webapp.py`/`contracts.py`/…") and large parts of `docs/STATES_AND_INTERACTIONS.md` predate the TS port. Rewrite as a follow-up — the high-level state machine still applies, but the file map is wrong.
- **Pre-port incident anecdotes** in `docs/CODING_RULES.md` reference `src/ariaflow_server/*.py` paths. The rules themselves are language-agnostic; a banner notes the discrepancy.
