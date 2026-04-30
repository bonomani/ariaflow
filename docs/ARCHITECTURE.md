# Ariaflow-server Engine Architecture

## Overview

Ariaflow-server is a headless download scheduler that manages queue state, sessions, runs, and policy. It delegates downloads to aria2 via JSON-RPC and exposes its state through a REST API. The web UI is a separate client.

## Core Concepts

The architecture is orthogonal — each concept answers exactly one question:

| Concept | Question | Examples |
|---|---|---|
| **Status / Readiness** | Can the system run safely? | Service status, preflight checks, dependency checks |
| **Policy** | How should the scheduler behave? | Concurrency, dedup, ordering, post-action rules |
| **Session** | Under which context is ariaflow-server operating? | session_id, started_at, closed_at, close_reason |
| **Run** | What is the scheduler doing now? | running, paused |
| **Queue** | What work exists and in what order? | Priority-ordered list of download items |
| **Group** | Which jobs belong together? | Named set of jobs within a queue |
| **Job** | What is the state of one download? | status, gid, url, mode, progress |

## Relationships

```
Status / Readiness  -->  tells if the system can start
Policy              -->  controls how Run / Queue / Group / Job behave
Session  -->  contains Run  -->  processes Queue  -->  contains Group  -->  contains Job
```

## Policy Placement

Policy applies where it changes behavior, not where it labels data.

| Policy | Belongs with | Scope |
|---|---|---|
| `preflight` | Readiness / run start | Can we start? |
| `concurrency` | Queue scheduling | How many simultaneous downloads? |
| `dedupe` | Queue selection | Skip duplicate URLs? |
| `group_priority` | Group ordering | Which group first? |
| `job_priority` | Job ordering | Which job first within a group? |
| `post_action_rule` | Job behavior | What happens after download? (global default) |

## Structural View

```
Status / Readiness
├── service status
├── preflight gates
└── dependency checks (aria2 daemon)

Policy
├── Run: mode (normal/debug), preflight (on/off)
├── Queue: concurrency, dedupe, ordering
├── Group: group_priority, recovery handling
└── Job: job_priority, post_action_rule

Session
├── session_id, started_at, last_seen_at, closed_at
└── Run
    ├── state: running / paused (auto-starts with serve)
    └── Queue
        ├── Group A (priority: 10)
        │   ├── Job A1 (priority: default, post_action: inherited)
        │   └── Job A2 (priority: 5, post_action: custom)
        └── Group B (priority: 3)
            └── Job B1

Observability
├── progress (speed, completion, ETA)
├── recent actions (actions.jsonl)
├── errors (error_code, error_message)
└── session history (sessions.jsonl)
```

## UIC Preferences (declaration.json)

These are the configurable preferences stored in `declaration.json`:

| Preference | Default | Description |
|---|---|---|
| `post_action_rule` | `"pending"` | Post-download action policy |
| `auto_preflight_on_run` | `false` | Run preflight checks before scheduler start |
| `duplicate_active_transfer_action` | `"remove"` | How to handle duplicate active downloads (`remove`, `pause`, `ignore`) |
| `max_simultaneous_downloads` | `1` | Max concurrent downloads (0 = unlimited) |
| `bandwidth_down_free_percent` | `20` | Percentage of downlink to keep free |
| `bandwidth_down_free_absolute_mbps` | `0` | Absolute Mbps to keep free (downlink) |
| `bandwidth_up_free_percent` | `50` | Percentage of uplink to keep free |
| `bandwidth_up_free_absolute_mbps` | `0` | Absolute Mbps to keep free (uplink) |
| `bandwidth_probe_interval_seconds` | `180` | Seconds between automatic bandwidth probes |

## UIC Gates (preflight)

| Gate | Class | Blocking | Description |
|---|---|---|---|
| `aria2_available` | readiness | hard | aria2 daemon must be reachable via RPC |
| `queue_readable` | integrity | hard | `queue.json` must be parseable |

## Design Rules

1. One term = one meaning
2. One layer = one question
3. One policy = one responsibility
4. Debug close to the object it explains
5. Noisy traces in the observability layer
6. No duplicate truths across files
7. Policy for defaults, not runtime identity
8. Orthogonal boundaries over clever abstractions

## Source Structure

The codebase is a pnpm workspace with three packages.

| Package | Role |
|---|---|
| `@ariaflow/core` (`packages/core/`) | Engine + libraries: scheduler loop, aria2 JSON-RPC client, queue/state stores, policy, contracts, discovery, install helpers |
| `@ariaflow/api` (`packages/api/`) | Fastify HTTP server: REST endpoints, SSE, freshness registry (`/api/_meta`), error envelope |
| `@ariaflow/cli` (`packages/cli/`) | `ariaflow` command: serve, doctor, queue ops |

Inside `packages/core/src/`:

| Subdir | Role |
|---|---|
| `aria2/` | JSON-RPC client, dispatch, option safety tiers |
| `bandwidth/` | networkQuality probe, units, config |
| `bonjour/` | mDNS service advertisement |
| `contracts/` | UIC gates + preferences (single source for declaration shape) |
| `discovery/` | Peer discovery via Bonjour browse |
| `events/` | In-process event bus consumed by SSE and the action log |
| `install/` | Homebrew formula generation, service installers |
| `platform/` | macOS launchd helpers |
| `queue/` | Item record types, policy, ops, summary |
| `reconcile/` | Item ↔ aria2 reconciliation |
| `routes/` | Path resolution and routing helpers |
| `scheduler/` | Loop, tick, poll, retry, dedup, post-action |
| `state/` | Archivable terminal-status logic |
| `storage/` | JSON stores with file-locking, paths |
| `torrent/` | Bencode + .torrent build/parse |
| `transfers/` | aria2 transfer status helpers |
