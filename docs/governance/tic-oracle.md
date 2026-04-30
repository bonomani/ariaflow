# TIC Oracle — ariaflow-server

Profile: ariaflow-server-scheduler
TIC ref: tic@7cfba80
Test runner: `pnpm test` (Vitest)
Test count: **513 tests** across 42 files

The Python test catalog (`tests/test_*.py`, 527 tests) was retired with
the Python source tree. The TypeScript port carries the same trace
targets, but the catalog now lives next to the code: each test file is
the leaf-level oracle, and trace-target intent is documented inline as
a comment on the `it(...)` block (e.g. `BG-30 #1: persists waiting
status`, `ASM CR-3: leaving the run-state`).

## Test inventory

Authoritative listing is the filesystem under `packages/*/src/**/*.test.ts`.
Run `pnpm test` to enumerate; vitest's reporter prints per-file test
counts and matches each `BG-N` / `ASM CR-N` reference to the
corresponding spec.

| Package | Path | Topic |
|---------|------|-------|
| core | `aria2/*.test.ts` | aria2 RPC client, dispatch, option tiers |
| core | `bandwidth/*.test.ts` | networkQuality probe, units, config |
| core | `bonjour/bonjour.test.ts` | mDNS announce |
| core | `contracts/*.test.ts` | UIC declaration + UCC envelope |
| core | `discovery/*.test.ts` | service discovery + registry |
| core | `events/bus.test.ts` | EventBus pub/sub |
| core | `install/*.test.ts` | Homebrew formula, services, install plan |
| core | `queue/*.test.ts` | QueueOps, policy (BG-30 status vocabulary) |
| core | `reconcile/reconcile.test.ts` | live-queue dedup, recovery |
| core | `routes/routes.test.ts` | route table |
| core | `scheduler/*.test.ts` | tick / poll / loop / retry / dedup / post-action / reconcile |
| core | `state/archivable.test.ts` | archive planner |
| core | `storage/*.test.ts` | StateStore / QueueStore / ActionLog / SessionService |
| core | `torrent/*.test.ts` | bencode, .torrent build |
| core | `transfers/transfers.test.ts` | active-transfer summary |
| api  | `server.test.ts` | Fastify routes (BG-1..32 contracts, freshness) |
| api  | `freshness.test.ts` | per-endpoint freshness registry (BG-31) |
| api  | `event-topics.test.ts` | SSE topic vocabulary (BG-32) |
| api  | `drift.test.ts` | OpenAPI drift detector |
| api  | `openapi.test.ts` | OpenAPI generation |
| cli  | `commands.test.ts` | cmdServe / cmdProbe / cmdDoctor / cmdDashboard / cmdWatch |
| cli  | `bin.test.ts` | CLI entry point |

## Trace targets

`BG-N` references in test descriptions point at the corresponding
entry in `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md` (resolved
section after the gap is closed). `ASM CR-N` references point at
the coherence rule in `asm-state-model.md`. Grep is the index:

```
git grep -nE "BG-[0-9]+|ASM CR-[0-9]+" packages
```

## When to update this file

- Test-count delta: update the header `**N tests**` figure and the
  matching count in `BGS.md` / `bgs-decision.yaml`.
- New test file under `packages/*/src/**/*.test.ts`: extend the
  inventory table above with its topic.
- New `BG-N` / `ASM CR-N` trace references appear: nothing to do
  here — the inline test description is the catalog entry.
