# Refactor Plan: Split core.py into Focused Modules — COMPLETED

## Status: Done

core.py split into 7 focused modules + re-export hub. All 374 tests pass. Zero behavior change.

## Context

`src/aria_queue/core.py` was 3091 lines with 100+ functions doing 6 different jobs. This refactor split it into focused modules, each answering one question (per ARCHITECTURE.md design rules). No behavior change, no API change.

## Module Map

```
src/aria_queue/
├── core.py             (~50 lines)   re-exports everything for backward compat
├── storage.py          (~180 lines)  file I/O, locking, paths
├── aria2_rpc.py        (~450 lines)  aria_rpc() + 36 aria2_* wrappers + add_download + ensure_daemon
├── state.py            (~200 lines)  load/save state, session lifecycle, action log
├── queue.py            (~500 lines)  QueueItem, load/save/add/pause/resume/remove/retry, priority
├── bandwidth.py        (~250 lines)  probe, apply, config, networkQuality
├── reconcile.py        (~250 lines)  reconcile_live_queue, deduplicate, cleanup_queue_state
├── scheduler.py        (~400 lines)  process_queue, start/stop_background_process, _poll_tracked_jobs
├── api.py              (unchanged)   re-exports from submodules
├── contracts.py        (unchanged)
├── webapp.py           (unchanged — imports from api.py, not core.py)
├── cli.py              (unchanged)
└── ...
```

## Function → Module Assignment

### `storage.py` — File I/O and locking

```
config_dir()                    34
queue_path()                    40
state_path()                    44
log_path()                      48
action_log_path()               52
archive_path()                  56
sessions_log_path()             60
storage_lock_path()             64
ensure_storage()                68
storage_locked()                73      ← context manager with fcntl + RLock
read_json()                     103
write_json()                    121

Constants:
  _STORAGE_LOCK                 19
  _STORAGE_LOCK_STATE           20
```

**Dependencies:** `json`, `os`, `fcntl`, `threading`, `pathlib`, `shutil`, `time`
**Depended on by:** everything

### `aria2_rpc.py` — aria2 JSON-RPC layer

```
aria_rpc()                      1692    ← low-level RPC caller
ensure_aria_daemon()            1721    ← spawns aria2c process
_is_metadata_url()              1752
aria2_add_uri()                 1762
aria2_add_torrent()             1780
aria2_add_metalink()            1799
add_download()                  1817    ← dispatcher: mode → aria2_add_*
aria2_tell_status()             1858
aria2_tell_active()             1929
aria2_tell_waiting()            1937
aria2_tell_stopped()            2131
aria2_get_files()               2111
aria2_get_uris()                2116
aria2_get_peers()               2121
aria2_get_servers()             2126
aria2_get_option()              2146
aria2_change_option()           2151
aria2_change_position()         2161
aria2_change_uri()              2170
aria2_get_global_stat()         2189
aria2_change_global_option()    2194
aria2_get_version()             2203
aria2_purge_download_result()   2211
aria2_get_session_info()        2219
aria2_save_session()            2224
aria2_shutdown()                2229
aria2_force_shutdown()          2234
aria2_pause()                   2060
aria2_force_pause()             2065
aria2_pause_all()               2070
aria2_force_pause_all()         2075
aria2_unpause()                 2080
aria2_unpause_all()             2085
aria2_remove()                  2093
aria2_force_remove()            2098
aria2_remove_download_result()  2103
aria2_multicall()               2242
aria2_list_methods()            2250
aria2_list_notifications()      2255
aria2_get_global_option()       2296
aria_status()                   2022    ← wraps get_version with error handling
set_bandwidth()                 2034    ← wraps change_global_option
set_download_bandwidth()        2042    ← wraps change_option
current_bandwidth()             2260    ← wraps get_global_option + state probe
current_global_options()        2301
change_aria2_options()          2320    ← safe subset validation

Constants:
  _BITS_PER_MEGABIT             21
  _BYTES_PER_MEGABIT            22
  _SAFE_ARIA2_OPTIONS           (set)

Helpers:
  _aria_speed_value()           1481
  _cap_bytes_per_sec_from_mbps() 1470
  _cap_mbps_from_bytes_per_sec() 1477
```

**Dependencies:** `storage.py` (config_dir, log_path), `urllib`, `json`, `subprocess`
**Depended on by:** `queue.py`, `bandwidth.py`, `reconcile.py`, `scheduler.py`

### `state.py` — State, sessions, action log, archive

```
load_state()                    247
save_state()                    266
ensure_state_session()          272
touch_state_session()           285
close_state_session()           294
start_new_state_session()       307
_log_session_history()          321
load_session_history()          352
session_stats()                 369
load_archive()                  401
save_archive()                  407
archive_item()                  412
auto_cleanup_queue()            421
_rotate_action_log()            134
append_action_log()             148
load_action_log()               168
record_action()                 185
log_transfer_poll()             213
```

**Dependencies:** `storage.py`
**Depended on by:** `queue.py`, `scheduler.py`

### `queue.py` — Queue items and per-item operations

```
ITEM_STATUSES                   569
_TERMINAL_STATUSES              670
QueueItem (dataclass)           624
detect_download_mode()          601
load_queue()                    652
summarize_queue()               658
save_queue()                    665
find_queue_item_by_url()        673
find_queue_item_by_gid()        711
_find_queue_item_by_id()        2454
_aria2_position_for_priority()  680
_apply_aria2_priority()         700
add_queue_item()                1306
pause_queue_item()              2464
resume_queue_item()             2510
remove_queue_item()             2582
retry_queue_item()              2634
get_item_files()                1872
select_item_files()             1891
dedup_active_transfer_action()  718
max_simultaneous_downloads()    730
_pref_value()                   744
active_status()                 2030
discover_active_transfer()      1949
format_bytes()                  2700
format_rate()                   2714
format_mbps()                   2720
post_action()                   2726
pause_active_transfer()         2348
resume_active_transfer()        2397
```

**Dependencies:** `storage.py`, `state.py`, `aria2_rpc.py`

### `bandwidth.py` — Bandwidth probing and control

```
bandwidth_config()              753
bandwidth_status()              778
_apply_free_bandwidth_cap()     800
manual_probe()                  815
_find_networkquality()          1450
_coerce_float()                 1461
_default_bandwidth_probe()      1485
_parse_networkquality_output()  1507
probe_bandwidth()               1562
_should_probe_bandwidth()       1611
_apply_bandwidth_probe()        1622

Constants:
  _NETWORKQUALITY_MAX_RUNTIME       23
  _NETWORKQUALITY_TIMEOUT           24
  _NETWORKQUALITY_PROBE_INTERVAL    25
  _NETWORKQUALITY_CANDIDATES        26
```

**Dependencies:** `storage.py`, `state.py`, `aria2_rpc.py` (set_bandwidth)

### `reconcile.py` — Queue reconciliation and deduplication

```
_active_item_url()              868
_queue_item_for_active_info()   885
_merge_active_status()          938
_queue_item_preference()        946
_merge_queue_rows()             961
_normalize_queue_row()          1001
cleanup_queue_state()           1023
reconcile_live_queue()          1084
deduplicate_active_transfers()  1236
```

**Dependencies:** `storage.py`, `state.py`, `aria2_rpc.py`, `queue.py` (load_queue, save_queue)

### `scheduler.py` — Main scheduler loop

```
start_background_process()      486
stop_background_process()       520
process_queue()                 2735    ← main loop with nested functions:
  _finalize_primary_state()       2680  (nested)
  _apply_transfer_fields()        2708  (nested)
  _queued_info()                  2714  (nested)
  _MAX_RPC_FAILURES               2725  (nested)
  _poll_tracked_jobs()            2727  (nested)
auto_preflight_on_run()         3057
get_active_progress()           3067
```

**Dependencies:** `storage.py`, `state.py`, `aria2_rpc.py`, `queue.py`, `bandwidth.py`, `reconcile.py`

### `core.py` — Re-export hub (backward compatibility)

```python
"""Backward-compatible re-export hub.

All public functions are importable from aria_queue.core.
New code should import from the specific submodule.
"""
from aria_queue.storage import *      # noqa: F401,F403
from aria_queue.aria2_rpc import *    # noqa: F401,F403
from aria_queue.state import *        # noqa: F401,F403
from aria_queue.queue import *        # noqa: F401,F403
from aria_queue.bandwidth import *    # noqa: F401,F403
from aria_queue.reconcile import *    # noqa: F401,F403
from aria_queue.scheduler import *    # noqa: F401,F403
```

## Dependency Graph

```
storage.py          (no internal deps — foundation)
    ↑
state.py            (depends on storage)
    ↑
aria2_rpc.py        (depends on storage)
    ↑
bandwidth.py        (depends on storage, state, aria2_rpc)
    ↑
queue.py            (depends on storage, state, aria2_rpc)
    ↑
reconcile.py        (depends on storage, state, aria2_rpc, queue)
    ↑
scheduler.py        (depends on everything above)
    ↑
core.py             (re-exports everything)
```

No circular dependencies. Each module only imports from modules above it.

## Implementation Steps

### Step 1: Create `storage.py`

Move path functions, `ensure_storage`, `storage_locked`, `read_json`, `write_json`, constants `_STORAGE_LOCK`, `_STORAGE_LOCK_STATE`.

**Checkpoint:** `pytest -x` — all tests pass (core.py still has everything, storage.py is new)

### Step 2: Create `aria2_rpc.py`

Move `aria_rpc`, all 36 `aria2_*` functions, `ensure_aria_daemon`, `add_download`, helpers, constants. Import `storage.py` for paths.

**Checkpoint:** `pytest -x` + `python scripts/gen_rpc_docs.py` (must still find all wrappers)

### Step 3: Create `state.py`

Move state/session/action-log/archive functions. Import `storage.py`.

**Checkpoint:** `pytest -x`

### Step 4: Create `queue.py`

Move QueueItem, item operations, status constants. Import `storage.py`, `state.py`, `aria2_rpc.py`.

**Checkpoint:** `pytest -x`

### Step 5: Create `bandwidth.py`

Move probe/bandwidth functions. Import `storage.py`, `state.py`, `aria2_rpc.py`.

**Checkpoint:** `pytest -x`

### Step 6: Create `reconcile.py`

Move reconciliation/dedup functions. Import `storage.py`, `state.py`, `aria2_rpc.py`, `queue.py`.

**Checkpoint:** `pytest -x`

### Step 7: Create `scheduler.py`

Move `process_queue`, `start/stop_background_process`, `get_active_progress`. Import everything.

**Checkpoint:** `pytest -x`

### Step 8: Replace `core.py` with re-export hub

Replace 3091-line core.py with ~10-line re-export file.

**Checkpoint:** `pytest -x` — all 374+ tests pass with zero behavior change.

### Step 9: Update `gen_rpc_docs.py`

Update introspection script to find wrappers in `aria2_rpc.py` instead of `core.py`.

**Checkpoint:** `python scripts/gen_rpc_docs.py` generates same output.

### Step 10: Update test mocks

Tests that patch `aria_queue.core.aria2_tell_status` etc. still work via re-exports. No changes needed unless a test imports a private function directly.

**Checkpoint:** Final `pytest -x`, verify count ≥ 374.

## What does NOT change

- `api.py` — imports from `core.py` which re-exports everything
- `webapp.py` — imports from `api.py`
- `cli.py` — imports from `core.py`
- `contracts.py` — independent
- All test files — patch `aria_queue.core.*` which still works via re-exports
- All docs — reference function names, not file paths

## Risks

| Risk | Mitigation |
|---|---|
| Circular imports | Dependency graph is acyclic (verified above) |
| Test mock paths break | `core.py` re-exports everything — `aria_queue.core.X` still works |
| `gen_rpc_docs.py` breaks | Step 9 updates it to scan `aria2_rpc.py` |
| Lazy imports in core.py (`from .contracts import`) | Move to the module that uses them |

## Estimated effort

- ~0 lines of new logic (pure move)
- ~50 lines for `core.py` re-export hub
- ~10 lines for import headers in each new module
- Each step has a checkpoint — can stop at any point
