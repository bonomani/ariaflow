# SSE Topic Vocabulary (BG-32)

`/api/events` is the single SSE endpoint. Clients can scope their
stream at connect time:

```
GET /api/events?topics=items,scheduler
```

Empty / missing `topics` query string → every event is delivered
(back-compat). Unknown topic names produce an empty subset (typo →
empty stream, not a firehose).

## Topics

| Topic       | Carries                                              |
|-------------|------------------------------------------------------|
| `items`     | Queue rows: status, progress, transitions            |
| `scheduler` | Scheduler loop / dispatch state, session lifecycle   |
| `log`       | Action log appends                                   |
| `lifecycle` | Service-manager (aria2 / ariaflow-server) state      |
| `bandwidth` | Probe results / cap changes                          |

## Event → topic mapping

| Event              | Topics                  |
|--------------------|-------------------------|
| `action_logged`    | `log`                   |
| `session_started`  | `scheduler`             |
| `session_closed`   | `scheduler`             |
| `state_changed`    | `items`, `scheduler`    |
| `lifecycle_changed`| `lifecycle`             |
| `bandwidth_probed` | `bandwidth`             |

Source of truth: `packages/api/src/event-topics.ts`. Unknown event
names default to **all topics** so a newly-introduced emitter is
visible to every subscriber until it's classified — the safe default
for an advisory filter. To classify a new event, add it to
`EVENT_TOPICS` in `event-topics.ts`.

## Discovery

The dashboard's `FreshnessRouter` reads `meta.transport_topics` from
`/api/_meta` so each `live` endpoint declares which topics carry its
updates. Today only `/api/status` is `live`, with
`transport_topics: ["items", "scheduler"]`.

## Changing topics mid-stream

V1 supports reconnect-with-different-`?topics=` only. In-stream
`POST /api/events/{subscribe,unsubscribe}` was considered but
deferred — adding per-connection identity to the bus is a bigger
change than the win, given EventSource will reconnect quickly.
