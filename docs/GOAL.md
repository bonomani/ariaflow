# Project Goal

Ariaflow is a **headless download scheduler** that puts an opinionated
state machine in front of `aria2c`. It exists so that automated and
agent-driven download workflows can rely on **explicit lifecycle
boundaries** instead of polling aria2 directly.

The scheduler owns the queue, the sessions, the runs, the active-job
limits, the preflight gates, and the per-item policy. `aria2` owns the
bytes-on-the-wire. Ariaflow translates between them through a REST API
+ Server-Sent Events stream so that any client (CLI, web UI,
machine-to-machine) sees the same coherent picture.

## Scope

In scope:
- Queue, session, run, and job state across restarts (`queue.json`,
  `state.json`, `archive.json`).
- Preflight gates (`aria2_available`, `queue_readable`) before any
  job becomes active.
- 36 aria2 RPC wrappers + orchestration helpers in `aria2_rpc.py`.
- HTTP API + SSE for clients; OpenAPI spec for contract enforcement.
- macOS integration: Homebrew install lifecycle, launchd unit,
  Bonjour/mDNS service discovery.
- Private BitTorrent distribution of completed downloads.
- Bandwidth probing via `networkQuality` and adaptive caps.

Out of scope (deliberate, see `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md`):
- Per-interface byte counters (use `htop` / Activity Monitor).
- Network-topology enumeration (privacy boundary).
- Multi-user authentication (it's a local CLI tool).
- File serving from the download directory (use a static HTTP server).

## Governance frame

Adoption is claimed under the
**`BGS-State-Modeled-Governed-Verified`** suite slice
(`docs/governance/BGS.md`). The slice mandates BISS classification,
ASM state model, UIC preflight, UCC execution semantics, and TIC test
oracle. The full decision record lives in
`docs/governance/bgs-decision.yaml`.

## How this file is used

`scripts/gen_spec.py` reads this file verbatim into Section 1 of
`docs/SPEC.md`. Edit this file by hand whenever the project's purpose
or scope changes; everything else in `SPEC.md` is auto-generated from
the code and the governance artifacts.
