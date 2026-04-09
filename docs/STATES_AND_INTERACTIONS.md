# States, Transitions, and Interactions — ariaflow-server Scheduler & aria2

**aria2 version supported:** 1.37.0 (JSON-RPC interface)

**Design rule:** All aria2 RPC methods listed below MUST have a corresponding `aria2_*` wrapper function in `core.py`, even if not currently used by the scheduler. This ensures the full aria2 API surface is available for future features and external consumers.

**See also:** [ARIA2_RPC_WRAPPERS.md](./ARIA2_RPC_WRAPPERS.md) — auto-generated reference of all 36 wrapper functions (regenerate with `python scripts/gen_rpc_docs.py`).

## Section 1: aria2 — States, Transitions, and RPC Commands

aria2 is an external download daemon. ariaflow-server communicates with it via JSON-RPC on port 6800.

### 1.1 aria2 Download States (6)

| Status | Type | Description |
|---|---|---|
| `waiting` | Queued | Queued in aria2, waiting for a concurrent download slot |
| `active` | Live | Currently downloading/uploading data |
| `paused` | Suspended | Paused by user; will not start until unpaused |
| `complete` | Terminal | Download finished successfully |
| `error` | Terminal | Download failed |
| `removed` | Terminal | Removed from aria2 via `remove`/`forceRemove` |

Terminal states (`complete`, `error`, `removed`) appear in `tellStopped()` and can be purged from memory.

### 1.2 aria2 State Transitions

```
                     addUri / addTorrent / addMetalink
                                │
                   ┌────────────▼────────────┐
                   │        waiting          │
                   └──┬──────────────────┬───┘
                      │                  │
              (slot available)     pause / forcePause
                      │                  │
                      ▼                  ▼
                 ┌──────────┐       ┌──────────┐
                 │  active  │◄──────│  paused  │  (unpause → waiting → active)
                 └──┬──┬──┬─┘       └────▲─────┘
                    │  │  │              │
         complete   │  │  │ error   pause / forcePause
                    │  │  │              │
                    │  │  └──────────────┘
                    ▼  ▼
             ┌──────────┐  ┌─────────┐
             │ complete │  │  error  │
             └──────────┘  └─────────┘

         remove / forceRemove (from any non-terminal) → removed
```

| From | To | Trigger | aria2 RPC Command |
|---|---|---|---|
| _(new)_ | `waiting` | Add download | `aria2.addUri`, `aria2.addTorrent`, `aria2.addMetalink` |
| _(new)_ | `paused` | Add with `--pause=true` | `aria2.addUri` (option `pause=true`) |
| `waiting` | `active` | Slot available | Automatic (respects `max-concurrent-downloads`) |
| `active` | `paused` | User pauses | `aria2.pause(gid)` or `aria2.forcePause(gid)` |
| `waiting` | `paused` | User pauses | `aria2.pause(gid)` or `aria2.forcePause(gid)` |
| `paused` | `waiting` | User unpauses | `aria2.unpause(gid)` |
| `active` | `complete` | Transfer finishes | Automatic |
| `active` | `error` | Transfer fails | Automatic |
| `active` | `removed` | User removes | `aria2.remove(gid)` or `aria2.forceRemove(gid)` |
| `waiting` | `removed` | User removes | `aria2.remove(gid)` or `aria2.forceRemove(gid)` |
| `paused` | `removed` | User removes | `aria2.remove(gid)` or `aria2.forceRemove(gid)` |

#### Graceful vs Force

| | Graceful (`pause`, `remove`) | Force (`forcePause`, `forceRemove`) |
|---|---|---|
| BitTorrent tracker | Contacts tracker to unregister | Skips |
| Cleanup | Performs all cleanup | Skips |
| Result | Same final state | Same final state |
| Use case | Normal operation | Immediate response needed |

### 1.3 aria2 RPC Methods Reference

#### Download Addition

| Method | Signature | Returns |
|---|---|---|
| `aria2.addUri` | `([secret], uris[], [options], [position])` | GID string |
| `aria2.addTorrent` | `([secret], torrent_base64, [uris], [options], [position])` | GID string |
| `aria2.addMetalink` | `([secret], metalink_base64, [options], [position])` | GID[] array |

#### Pause / Resume

| Method | Signature | Behavior |
|---|---|---|
| `aria2.pause` | `([secret], gid)` | Graceful pause (contacts BT trackers) |
| `aria2.forcePause` | `([secret], gid)` | Immediate pause |
| `aria2.pauseAll` | `([secret])` | Pause all downloads (graceful) |
| `aria2.forcePauseAll` | `([secret])` | Pause all downloads (immediate) |
| `aria2.unpause` | `([secret], gid)` | Resume: paused → waiting |
| `aria2.unpauseAll` | `([secret])` | Resume all paused downloads |

#### Remove

| Method | Signature | Behavior |
|---|---|---|
| `aria2.remove` | `([secret], gid)` | Graceful stop + remove |
| `aria2.forceRemove` | `([secret], gid)` | Immediate remove |

#### Status Query

| Method | Signature | Returns |
|---|---|---|
| `aria2.tellStatus` | `([secret], gid, [keys])` | Status dict (gid, status, totalLength, completedLength, downloadSpeed, errorCode, errorMessage, files, ...) |
| `aria2.tellActive` | `([secret], [keys])` | Array of status dicts |
| `aria2.tellWaiting` | `([secret], offset, num, [keys])` | Array of status dicts |
| `aria2.tellStopped` | `([secret], offset, num, [keys])` | Array of status dicts |
| `aria2.getUris` | `([secret], gid)` | Array of URI objects (uri, status) |
| `aria2.getFiles` | `([secret], gid)` | Array of file objects |
| `aria2.getPeers` | `([secret], gid)` | Array of peer objects (BitTorrent only) |
| `aria2.getServers` | `([secret], gid)` | Array of server objects (HTTP/FTP only) |

#### Global

| Method | Signature | Returns |
|---|---|---|
| `aria2.getGlobalStat` | `([secret])` | downloadSpeed, uploadSpeed, numActive, numWaiting, numStopped |
| `aria2.getVersion` | `([secret])` | version, enabledFeatures |
| `aria2.getSessionInfo` | `([secret])` | sessionId |

#### Options

| Method | Signature | Behavior |
|---|---|---|
| `aria2.changeOption` | `([secret], gid, options)` | Set per-GID options |
| `aria2.getOption` | `([secret], gid)` | Get per-GID options |
| `aria2.changeGlobalOption` | `([secret], options)` | Set global options (e.g. `max-overall-download-limit`) |
| `aria2.getGlobalOption` | `([secret])` | Get global options |

#### Queue Management

| Method | Signature | Behavior |
|---|---|---|
| `aria2.changePosition` | `([secret], gid, pos, how)` | Move in queue (`POS_SET`, `POS_CUR`, `POS_END`) |
| `aria2.changeUri` | `([secret], gid, fileIndex, delUris, addUris, [position])` | Swap URIs |

#### Cleanup & Session

| Method | Signature | Behavior |
|---|---|---|
| `aria2.purgeDownloadResult` | `([secret])` | Remove all terminal downloads from memory |
| `aria2.removeDownloadResult` | `([secret], gid)` | Remove one terminal download from memory |
| `aria2.saveSession` | `([secret])` | Save session to file |
| `aria2.shutdown` | `([secret])` | Graceful shutdown |
| `aria2.forceShutdown` | `([secret])` | Immediate shutdown |

#### System

| Method | Signature | Returns |
|---|---|---|
| `system.multicall` | `(methods[])` | Array of results — batch multiple RPC calls in one request |
| `system.listMethods` | `()` | Array of all available RPC method names |
| `system.listNotifications` | `()` | Array of all supported notification names |

#### Notifications (WebSocket)

| Notification | Trigger |
|---|---|
| `aria2.onDownloadStart` | Download started |
| `aria2.onDownloadPause` | Download paused |
| `aria2.onDownloadStop` | Download stopped (removed) |
| `aria2.onDownloadComplete` | Download completed |
| `aria2.onDownloadError` | Download failed |
| `aria2.onBtDownloadComplete` | BT content complete (may still seed) |

---

## Section 2: ariaflow-server Scheduler — States and Transitions

### 2.1 Scheduler States (3)

The scheduler auto-starts with `ariaflow serve` and runs continuously until shutdown. There is no idle state and no start/stop API — users can only pause/resume.

```
    ariaflow serve
         │
         ▼
    ┌──────────┐   POST /api/scheduler/pause    ┌────────┐
    │ starting │──►┌──────────┐◄────────────────│ paused │
    └──────────┘   │ running  │────────────────►└────────┘
                   └──────────┘   POST /api/scheduler/resume
```

| State | `running` | `paused` | Description |
|---|---|---|---|
| **starting** | false | false | Brief state before scheduler thread starts |
| **running** | true | false | Scheduling and polling items every 2 s |
| **paused** | true | true | Loop active but skips scheduling. Active aria2 downloads paused |

| Transition | Trigger | What happens |
|---|---|---|
| starting → running | `ariaflow serve` | Spawns daemon thread running `process_queue()` |
| running → paused | `POST /api/scheduler/pause` | `aria2.pause(gid)` on all active GIDs; `state.paused = true` |
| paused → running | `POST /api/scheduler/resume` | `aria2.unpause(gid)` on all paused GIDs; `state.paused = false` |

### 2.2 Queue Model — Hybrid (queue.json + aria2)

**Design:** `queue.json` is the persistent source of truth. aria2 is the volatile executor. Items are submitted eagerly to aria2 when available, with `queued` as a safety-net fallback when aria2 is unreachable.

```
    queue.json (persistent)          aria2 (executor)                ariaflow-server
    ───────────────────────    ──────────────────────────────    ──────────────

    ┌─────────────┐
    │ discovering │  mode detection
    └──────┬──────┘
           │ eager submit
           ▼
    ┌──────────┐  aria2.addUri   ┌──────────┐    ┌────────┐    ┌──────────┐
    │  queued  │ ──────────────► │ waiting  │──► │ active │──► │ complete │
    └──────────┘  (fallback if   └──────────┘    └────────┘    └──────────┘
    safety net    aria2 down)     aria2 owns      aria2 owns   post_action()
```

**Six design principles:**

1. **queue.json is always the source of truth.** Survives aria2 crashes, restarts, power failures.
2. **Submit eagerly.** Items go to aria2 immediately at add time when scheduler is running. No lazy 2s-loop submission.
3. **Delegate concurrency to aria2.** `aria2_change_global_option({max-concurrent-downloads: N})` at scheduler start. No ariaflow-server slot-gating.
4. **Delegate priority to aria2.** After submission, `aria2_change_position` reorders aria2's queue by ariaflow-server priority.
5. **`queued` is a safety net.** Items only stay `queued` when aria2 is unreachable or submission fails.
6. **Reconcile on startup.** Compare queue.json to aria2 live state. Re-submit `queued` items. Adopt orphaned aria2 downloads.

**What ariaflow-server owns:**
- Pre-submission: mode detection, validation
- Metadata: URL, post_action_rule, session_id, timestamps, session_history
- Post-completion: post_action execution
- Bandwidth probing and cap application
- Session lifecycle, API surface, audit logging

**What ariaflow-server delegates to aria2:**
- Queue ordering (`aria2_change_position`)
- Concurrency (`aria2_change_global_option({max-concurrent-downloads})`)
- Download state (active, waiting, paused, complete, error, removed)
- Pause/resume (`aria2_pause`, `aria2_unpause`, `aria2_pause_all`, `aria2_unpause_all`)

### 2.3 Item States (9)

| Status | Type | Owner | Description |
|---|---|---|---|
| `discovering` | Transitional | ariaflow-server | Auto-detecting download mode, then eager submission |
| `queued` | Stable | ariaflow-server | Safety net — waiting for aria2 (unreachable or submission failed) |
| `waiting` | Stable | aria2 | In aria2's queue, not yet active |
| `active` | Transitional | aria2 | Active transfer (aria2 `active`) |
| `paused` | Stable | aria2 | Transfer suspended |
| `complete` | Terminal | ariaflow-server | Completed — post-action runs (aria2 `complete`) |
| `error` | Terminal | ariaflow-server | Failed (retryable via retry) |
| `stopped` | Terminal | ariaflow-server | Stopped by scheduler shutdown or aria2 `removed` |
| `cancelled` | Terminal | ariaflow-server | Cancelled by user, archived |

### 2.4 State Transitions

| From | To | Trigger | aria2 RPC | Phase |
|---|---|---|---|---|
| `discovering` → `queued` | Mode resolved, aria2 unreachable | _(none)_ | pre-submission fallback |
| `discovering` → `active` | Mode resolved, eager submission succeeds | `aria2_add_uri` / `aria2_add_torrent` / `aria2_add_metalink` | eager submission |
| `queued` → `active` | Main loop submits to aria2 | `aria2_add_uri` + `aria2_change_position` | deferred submission |
| `active` → `waiting` | aria2 reports `waiting` | _(poll via `aria2_tell_status`)_ | aria2-owned |
| `waiting` → `active` | aria2 slot available | _(poll via `aria2_tell_status`)_ | aria2-owned |
| `active` → `complete` | aria2 reports `complete` | _(poll via `aria2_tell_status`)_ | post-completion |
| `active` → `error` | aria2 reports `error` or 5× RPC failures | _(poll via `aria2_tell_status`)_ | aria2-owned |
| `active` → `paused` | `POST /api/downloads/{id}/pause` | `aria2_pause(gid)` | aria2-owned |
| `active` → `stopped` | aria2 reports `removed` | _(poll via `aria2_tell_status`)_ | aria2-owned |
| `paused` → `active` | `POST /api/downloads/{id}/resume` (has GID) | `aria2_unpause(gid)` | aria2-owned |
| `paused` → `queued` | `POST /api/downloads/{id}/resume` (no GID) | _(eager re-submission attempted)_ | fallback |
| `queued`/`paused` → `cancelled` | `POST /api/downloads/{id}/remove` | `aria2_remove(gid)` + `aria2_remove_download_result(gid)` | removal |
| `error` → `queued` | `POST /api/downloads/{id}/retry` | _(eager re-submission attempted)_ | fallback |

### 2.5 Session States (3)

| State | Description |
|---|---|
| **none** | No session exists (`session_id = null`) |
| **open** | Session active, accepting work |
| **closed** | Session ended with a reason |

Close reasons: `queue_complete`, `closed`, `manual_new_session`.

---

## Section 3: Interaction — Scheduler ↔ aria2

### 3.1 Startup Sequence

```
1. ensure_aria_daemon()
   ├── aria2.getVersion()              check if running
   │   ├── success → already running
   │   └── fail → spawn aria2c --enable-rpc --rpc-listen-port=6800
   │       └── aria2.getVersion()      verify started
   │
2. deduplicate_active_transfers()
   ├── aria2.tellActive()              list all active GIDs
   ├── group by URL
   ├── keep best-progress per URL
   └── aria2.remove(duplicate_gid)     remove duplicates
   │
3. reconcile_live_queue()
   ├── aria2.tellActive()              list all active GIDs
   ├── match to queue items by GID/URL
   └── adopt orphaned aria2 jobs into queue
```

### 3.2 Main Loop (every 2 s)

```
┌─────────────────────────────────────────────────────────┐
│  Phase 1: Load (file-locked)                            │
│  ├── load queue.json                                    │
│  ├── load state.json                                    │
│  └── check paused flag                                   │
├─────────────────────────────────────────────────────────┤
│  Phase 2: RPC calls (unlocked)                          │
│  ├── _poll_tracked_jobs()                               │
│  │   └── for each item with gid:                        │
│  │       └── aria2.tellStatus(gid)                      │
│  │           active   → item.status = active            │
│  │           waiting  → item.status = waiting           │
│  │           paused   → item.status = paused            │
│  │           complete → item.status = complete          │
│  │           error    → item.status = error             │
│  │           removed  → item.status = stopped           │
│  │           RPC fail ×5 → item.status = error          │
│  │                                                       │
│  ├── _apply_bandwidth_probe()                           │
│  │   └── if interval elapsed: probe then                │
│  │       aria2.changeGlobalOption                       │
│  │         ({max-overall-download-limit: cap_bytes})    │
│  │                                                       │
│  └── Schedule new downloads (if not paused):            │
│      └── for each queued item (priority order):         │
│          └── aria2.addUri / addTorrent / addMetalink    │
│          └── respect max_simultaneous_downloads slots   │
├─────────────────────────────────────────────────────────┤
│  Phase 3: Save (file-locked)                            │
│  ├── save queue.json + state.json                       │
│  └── all items terminal? → close session, exit loop     │
├─────────────────────────────────────────────────────────┤
│  sleep(2) → repeat                                      │
└─────────────────────────────────────────────────────────┘
```

### 3.3 Global Pause / Resume

```
POST /api/scheduler/pause:
  ├── aria2.tellActive()
  ├── aria2.pause(gid)  for each
  ├── state.paused = true
  └── loop continues, skips scheduling

POST /api/scheduler/resume:
  ├── aria2.unpause(gid)  for each paused item
  ├── state.paused = false
  └── loop resumes scheduling
```

### 3.4 Per-Item Actions → aria2 RPC Mapping

| API Endpoint | aria2 RPC Calls |
|---|---|
| `POST /api/downloads/{id}/pause` | `aria2.pause(gid)` |
| `POST /api/downloads/{id}/resume` | `aria2.unpause(gid)` (or none if no GID) |
| `POST /api/downloads/{id}/remove` | `aria2.remove(gid)` then `aria2.removeDownloadResult(gid)` |
| `POST /api/downloads/{id}/retry` | _(none — clears GID, re-queues for scheduling)_ |

### 3.5 Download Mode → aria2 RPC

| Mode | Detection | RPC Method | Extra Options |
|---|---|---|---|
| `http` | Default | `aria2.addUri([url])` | max-download-limit, allow-overwrite, continue |
| `magnet` | `magnet:` prefix | `aria2.addUri([url])` | + pause-metadata=true |
| `torrent` | `.torrent` extension | `aria2.addUri([url])` | + pause-metadata=true |
| `metalink` | `.metalink`/`.meta4` | `aria2.addUri([url])` | + pause-metadata=true |
| `mirror` | Multiple URLs | `aria2.addUri([url1, url2, ...])` | + pause-metadata=true |
| `torrent_data` | Base64 .torrent | `aria2.addTorrent(base64)` | pause-metadata=true |
| `metalink_data` | Base64 metalink | `aria2.addMetalink(base64)` | Returns GID[] |

### 3.6 Bandwidth Control

```
Automatic every bandwidth_probe_interval_seconds (default 180s)
  or manual via POST /api/bandwidth/probe:

  ├── probe_bandwidth()
  │   └── macOS: networkQuality -u -c -s -M 8  (timeout: 10s, max runtime: 8s)
  │       searches: /usr/bin/networkQuality, /usr/bin/networkquality,
  │       /System/Library/PrivateFrameworks/.../networkQuality
  │
  ├── Calculate cap:
  │   ├── down_cap = downlink × (1 - bandwidth_down_free_percent / 100)
  │   ├── if bandwidth_down_free_absolute_mbps > 0:
  │   │   down_cap = min(down_cap, downlink - free_absolute)
  │   └── same logic for uplink
  │
  └── Apply:
      ├── aria2.changeGlobalOption({max-overall-download-limit: cap_bytes_per_sec})
      └── per-GID: aria2.changeOption(gid, {max-download-limit: cap_bytes_per_sec})

Probe result stored in state.json as last_bandwidth_probe:
  interface_name, downlink_mbps, uplink_mbps, down_cap_mbps, up_cap_mbps,
  cap_mbps, cap_bytes_per_sec, responsiveness_rpm, source, reason
```

### 3.7 State File Summary

All files under `~/.config/aria-queue/` (override: `ARIA_QUEUE_DIR`), accessed under fcntl file lock.

| File | Content |
|---|---|
| `state.json` | `running`, `paused`, `session_id`, `session_started_at`, `session_last_seen_at`, `session_closed_at`, `session_closed_reason`, `active_gid`, `active_url`, `last_bandwidth_probe`, `last_bandwidth_probe_at`, `_rev` |
| `queue.json` | `{items: [...]}` — each item has: id, url, status, mode, priority, gid, output, mirrors, torrent_data, metalink_data, session_id, timestamps, error fields, live_status, progress fields |
| `archive.json` | Soft-deleted items (cancelled, cleaned up) |
| `declaration.json` | UIC gates, preferences (concurrency, bandwidth, dedup policy), policies |
| `actions.jsonl` | Audit log of all operations (auto-rotated at 512 KB) |
| `sessions.jsonl` | Session history (appended on session close) |
| `.storage.lock` | fcntl `LOCK_EX` + thread `RLock` for mutual exclusion |
