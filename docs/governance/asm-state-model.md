# ASM State Model — Ariaflow

Profile: ariaflow-scheduler
ASM ref: asm@dca032b

## 1. State Axes

### Axis 1: Session (lifecycle container)

| Atomic State | Role | Description |
|---|---|---|
| `none` | terminal | No session exists |
| `open` | stable | Session active, accepting work |
| `closed` | terminal | Session ended, reason recorded |

Stored fields: `session_id`, `session_started_at`, `session_last_seen_at`, `session_closed_at`, `session_closed_reason`

### Axis 2: Run (execution cycle)

| Atomic State | Role | Description |
|---|---|---|
| `idle` | stable | No run in progress (`running: false`) |
| `running` | stable | Run loop active (`running: true`) |
| `paused` | stable | Run loop suspended (`paused: true`) |
| `stop_requested` | transitional | Stop signal sent, draining (`stop_requested: true`) |

Stored fields: `running`, `paused`, `stop_requested`

### Axis 3: Job (unit of work)

| Atomic State | Role | Description |
|---|---|---|
| `discovering` | transitional | Auto-detecting download mode (instant) |
| `queued` | stable | Ready for scheduling (priority-ordered) |
| `downloading` | transitional | Active transfer in progress |
| `paused` | stable | Transfer suspended by user |
| `done` | terminal | Transfer completed successfully |
| `error` | terminal | Transfer failed (retryable via retry) |
| `stopped` | terminal | Stopped by af-scheduler shutdown or GID removed |
| `cancelled` | terminal | Cancelled by user (soft-deleted to archive) |

Download modes: `http`, `magnet`, `torrent`, `metalink`, `mirror`, `torrent_data`, `metalink_data`

Live sub-state (aria2): `active`, `waiting` (mapped via `live_status` field)

### Axis 4: Daemon (aria2 process)

| Atomic State | Role | Description |
|---|---|---|
| `absent` | stable | aria2 not running |
| `available` | stable | aria2 reachable via RPC |
| `unreachable` | recovery | aria2 expected but not responding |

Checked dynamically via RPC probe, not persisted.

## 2. Derived States

| Derived State | Computed From | Meaning |
|---|---|---|
| `scheduler_ready` | session=open, run=idle, daemon=available | Scheduler can accept a run command |
| `scheduler_active` | session=open, run=running, daemon=available | Scheduler is processing the queue |
| `scheduler_draining` | session=open, run=stop_requested | Scheduler is finishing current job before stopping |
| `queue_complete` | run=running, all jobs terminal | No more work; triggers session close |

## 3. Transition Catalog

### Session transitions

```
none → open             ensure_state_session()
open → open             touch_state_session() (heartbeat)
open → closed           close_state_session(reason)
closed → open           start_new_state_session()
```

Close reasons: `stop_requested`, `queue_complete`, `closed`, `manual_new_session`

### Run transitions

```
idle → running          run loop starts
running → paused        pause command
paused → running        resume command
running → stop_requested   stop command
stop_requested → idle   drain complete
```

### Job transitions

```
discovering → queued    mode detected (synchronous)
queued → downloading    scheduler picks job
downloading → done      aria2 reports success
downloading → error     aria2 reports failure
downloading → stopped   run stops mid-transfer
downloading → paused    pause command
paused → queued         resume command (no gid)
paused → downloading    resume command (with gid)
queued → cancelled      user removes (archived)
paused → cancelled      user removes (archived)
error → queued          retry (re-queue)
error → cancelled       user removes (archived)
```

## 4. Coherence Rules

| Rule | Invariant |
|---|---|
| CR-1 | `run=running` requires `session=open` |
| CR-2 | `run=running` requires `daemon=available` |
| CR-3 | `job=downloading` requires `run=running` |
| CR-4 | `run=stop_requested` must eventually reach `run=idle` |
| CR-5 | `session=closed` requires all jobs not in `downloading` |
| CR-6 | At most `max_simultaneous_downloads` jobs in `downloading` at any time |

## 5. State Persistence

- **Scheduler state** (`state.json`): session + run axes — persisted atomically under file lock
- **Queue state** (`queue.json`): job axis — persisted atomically under same file lock
- **Daemon state**: not persisted, probed at runtime via RPC

Lock mechanism: `fcntl.LOCK_EX` on `.storage.lock` + thread-level `RLock`
