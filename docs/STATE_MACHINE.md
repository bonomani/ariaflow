# Download Item State Machine

Canonical vocabulary for `item.status`. aria2-native names where possible
(`active`/`waiting`/`paused`/`error`/`complete`/`removed`); two
backend-only staging states (`discovering`/`queued`) cover the
pre-aria2 hand-off.

## States

| Status        | Tier     | Terminal | Description |
|---------------|----------|----------|-------------|
| `discovering` | backend  | no       | Item created, waiting on metadata (e.g. magnet → torrent) |
| `queued`      | backend  | no       | Ready to dispatch; waiting on cap/concurrency |
| `active`      | aria2    | no       | aria2 is currently downloading the item |
| `waiting`     | aria2    | no       | aria2 has accepted the gid but throttled it |
| `paused`      | aria2    | no       | User paused this single item via aria2.pause |
| `complete`    | aria2    | yes      | Download finished successfully |
| `error`       | aria2    | yes      | Download failed (aria2 reported error) |
| `removed`     | aria2    | yes      | User removed the item via aria2.remove (canonical) |
| `stopped`     | alias    | yes      | Legacy alias of `removed`, retained for one release (BG-30) |

## Transitions

```
discovering ─→ queued ─→ active ⇄ waiting ⇄ paused
                  │         │
                  │         └─→ complete | error | removed
                  └─→ removed (user remove before dispatch)
```

| From          | To           | Trigger                                              |
|---------------|--------------|------------------------------------------------------|
| (new)         | `discovering`| `POST /api/downloads` for magnet without metadata    |
| (new)         | `queued`     | `POST /api/downloads` (URL/torrent/metalink)         |
| `discovering` | `queued`     | scheduler resolves metadata                          |
| `queued`      | `active`     | `runSchedulerTick` dispatches to aria2               |
| `queued`      | `removed`    | user `POST /api/downloads/<id>/remove` pre-dispatch  |
| `active`      | `waiting`    | poller observes aria2 `tellActive.status="waiting"`  |
| `waiting`     | `active`     | poller observes aria2 `tellActive.status="active"`   |
| `active`      | `paused`     | user `POST /api/downloads/<id>/pause`                |
| `paused`      | `active`     | user `POST /api/downloads/<id>/resume`               |
| `active`      | `complete`   | poller: `tellStatus.status="complete"`               |
| `active`      | `error`      | poller: `tellStatus.status="error"`                  |
| `active`      | `removed`    | user `POST /api/downloads/<id>/remove`               |
| `error`       | `queued`     | retry pass (`runRetryPass`) re-arms after backoff    |

## Scheduler-level state (separate axis)

`state.dispatch_paused` (canonical, BG-30 #4) — when true, the loop
stops dispatching new items but still polls aria2 for transitions.
Item-level `paused` is unrelated: a single download paused by the
user. The legacy `state.paused` JSON key is dual-keyed for one
release.

| Endpoint                 | Effect                                  |
|--------------------------|-----------------------------------------|
| `POST /api/scheduler/pause`  | `state.dispatch_paused = true`      |
| `POST /api/scheduler/resume` | `state.dispatch_paused = false` + auto-start loop |
| `POST /api/scheduler/start`  | start loop if `running=false`       |
| `POST /api/scheduler/stop`   | abort loop                          |

## Active gid (live, derived)

`state.active_gid` / `state.active_url` are derived from
`aria2.tellActive()` at `/api/status` read time (BG-30 #5). The
stamped state values are kept as a fallback for when aria2 is
unreachable so callers can still see the last-known active id.
