# Ariaflow Frontend Guide

## 1. Queue System

### 1.1 Queue Item

Every download is a **queue item** with these fields:

| Field | Type | Description |
|---|---|---|
| `id` | string (UUID) | Unique identifier — use this for all per-item API calls |
| `url` | string | Primary download URL |
| `status` | string | Current state (see §1.2) |
| `mode` | string | Download mode (see §1.3) |
| `priority` | int | Scheduling order — higher = processed first (default 0) |
| `gid` | string \| null | aria2 job ID — null until download starts |
| `output` | string \| null | Custom output filename |
| `post_action_rule` | string | Post-download action policy (default `"pending"`) |
| `mirrors` | string[] \| null | Additional mirror URLs (mode=mirror) |
| `torrent_data` | string \| null | Base64 .torrent file content (mode=torrent_data) |
| `metalink_data` | string \| null | Base64 metalink XML content (mode=metalink_data) |
| `session_id` | string \| null | Session that owns this item |
| `recovery_session_id` | string \| null | Session that recovered this item |
| `created_at` | ISO 8601 | When the item was added |
| `paused_at` | ISO 8601 \| null | When last paused |
| `resumed_at` | ISO 8601 \| null | When last resumed |
| `completed_at` | ISO 8601 \| null | When download finished |
| `error_at` | ISO 8601 \| null | When error occurred |
| `removed_at` | ISO 8601 \| null | When removed from queue |
| `cancelled_at` | ISO 8601 \| null | When user cancelled |
| `error_code` | string \| null | aria2 error code or `rpc_unreachable` |
| `error_message` | string \| null | Human-readable error description |
| `live_status` | string \| null | Raw aria2 status (`active`, `waiting`, `paused`) |
| `downloadSpeed` | string \| null | Current speed in bytes/s |
| `completedLength` | string \| null | Bytes downloaded |
| `totalLength` | string \| null | Total file size in bytes |
| `post_action` | object \| null | Post-download action result (set on completion) |
| `session_history` | object[] \| null | Session migration log |

### 1.2 Item States

```
    ┌─────────────┐
    │ discovering  │  mode auto-detection (instant)
    └──────┬──────┘
           │ eager submit
           ▼
    ┌──────────┐  submit   ┌──────────┐    ┌────────┐
    │  queued  │ ────────► │ waiting  │──► │ active │
    └──────────┘ (fallback └──────────┘    └┬──┬──┬─┘
     safety net  if aria2               pause│  │  │
                 down)                       │  │  │error/
           ┌─────────────────────────────────┘  │  │removed
           ▼                                    │  │
    ┌──────────┐   ┌──────────┐                 │  │
    │  paused  │   │ complete │◄────────────────┘  │
    └──────┬───┘   └──────────┘  aria2 complete    │
           │                                       ▼
     resume│                    ┌──────────┐  ┌─────────┐
           └───────────────────►│  error   │  │ stopped │
              (re-queue)        └────┬─────┘  └─────────┘
                                     │ retry
                                     ▼
                                (back to queued)

    Any state ──── user removes ────► cancelled (archived)
```

| Status | Terminal? | User actions available |
|---|---|---|
| `discovering` | No | — (instant, frontend rarely sees this) |
| `queued` | No | remove, change priority (safety net — aria2 unreachable) |
| `waiting` | No | pause, remove |
| `active` | No | pause, remove |
| `paused` | No | resume, remove |
| `complete` | Yes | remove (archive) |
| `error` | Yes | retry, remove |
| `stopped` | Yes | retry, remove |
| `cancelled` | Yes | — (already archived) |

**Frontend tips:**
- Show retry button only for `error` and `stopped`
- Show pause button only for `waiting` and `active`
- Show resume button only for `paused`
- Show remove button for all non-cancelled states
- Items in `complete`/`error`/`stopped` stay in queue until user removes or auto-cleanup runs

### 1.3 Download Modes

Mode is auto-detected from the URL when adding. The frontend can display an icon or badge per mode.

| Mode | Detected from | Behavior |
|---|---|---|
| `http` | `http://`, `https://`, `ftp://` | Direct download |
| `magnet` | `magnet:?` | BitTorrent via magnet link |
| `torrent` | `.torrent` URL | Downloads metadata, pauses for file selection |
| `metalink` | `.metalink`, `.meta4` URL | Downloads metadata, pauses for file selection |
| `mirror` | `mirrors` array provided | Downloads from multiple URLs simultaneously |
| `torrent_data` | `torrent_data` field (base64) | Direct .torrent upload |
| `metalink_data` | `metalink_data` field (base64) | Direct metalink XML upload |

**Torrent/metalink file selection flow:**
1. User adds a `.torrent` URL → item becomes `queued` with `mode=torrent`
2. Engine downloads metadata and pauses → item gets a `gid`
3. Frontend calls `GET /api/item/{id}/files` → shows file picker
4. User selects files → frontend calls `POST /api/item/{id}/files` with `{select: [1,3,5]}`
5. Item transitions to `active`

### 1.4 Queue Operations

#### Add items
```
POST /api/add
{
  "items": [
    {
      "url": "https://example.com/file.bin",
      "output": "custom-name.bin",        // optional
      "priority": 10,                      // optional, default 0
      "mirrors": ["https://mirror2.com/file.bin"],  // optional
      "torrent_data": "base64...",         // optional, for direct upload
      "metalink_data": "base64..."         // optional, for direct upload
    }
  ]
}
→ { "ok": true, "count": 1, "added": [{ item... }] }
```

- Duplicate URLs return the existing item (no new item created)
- Mode is auto-detected — no need to specify it
- `priority` determines scheduling order: higher values go first

#### Per-item actions
```
POST /api/item/{id}/pause    → { "ok": true, "item": {...} }
POST /api/item/{id}/resume   → { "ok": true, "item": {...} }
POST /api/item/{id}/remove   → { "ok": true, "removed": true }
POST /api/item/{id}/retry    → { "ok": true, "item": {...} }
```

Each returns the updated item (or confirmation). All actions:
- Validate state (e.g. can't pause an already-paused item → 400)
- Return 404 if item not found
- Record the action in the action log
- Trigger SSE `state_changed` event

#### File selection (torrent/metalink)
```
GET  /api/item/{id}/files           → { "files": [...] }
POST /api/item/{id}/files           → { "ok": true, "selected": [1,3] }
     body: { "select": [1, 3, 5] }
```

#### Read queue
```
GET /api/status                     → full queue + state + summary
GET /api/status?status=queued       → only queued items
GET /api/status?status=queued,paused → multiple statuses
GET /api/status?session=current     → only current session's items
GET /api/status?status=error&session=current  → combinable
```

The response always includes:
```json
{
  "items": [...],
  "state": { "running": false, "paused": false, "session_id": "..." },
  "summary": { "total": 5, "queued": 2, "waiting": 0, "active": 1, "paused": 0, "complete": 1, "error": 1, "stopped": 0, "cancelled": 0, "discovering": 0 },
  "ariaflow": { "version": "0.1.58", "schema_version": "1" },
  "_rev": 42,
  "_schema": "1",
  "_request_id": "uuid"
}
```

#### Archive (removed items)
```
GET /api/archive?limit=100   → { "items": [...] }
```

Removed items are soft-deleted here. Useful for "recently removed" UI or undo.

#### Auto-cleanup
```
POST /api/cleanup
{ "max_done_age_days": 7, "max_done_count": 100 }
→ { "ok": true, "archived": 3, "remaining": 12 }
```

Moves stale complete/error items to archive automatically.

### 1.5 Priority Scheduling

Items are processed in **priority order** (higher first, then FIFO within same priority).

```
POST /api/add  { "items": [
  {"url": "...", "priority": 0},    // normal
  {"url": "...", "priority": 10},   // processed first
  {"url": "...", "priority": -1}    // processed last
]}
```

The frontend can expose this as:
- Drag-and-drop reordering (map position to priority)
- "Move to top" button (set priority = max + 1)
- Priority badge or number input

### 1.6 Progress Display

For active items, use these fields to render progress:

```javascript
const item = status.items.find(i => i.status === 'active');
const completed = parseInt(item.completed_length || '0');
const total = parseInt(item.total_length || '0');
const speed = parseInt(item.downloadSpeed || '0');
const percent = total > 0 ? (completed / total * 100).toFixed(1) : null;
const eta = speed > 0 ? Math.round((total - completed) / speed) : null;
```

`live_status` gives the raw aria2 state:
- `active` = transferring data
- `waiting` = queued in aria2 (slot limit reached)
- `paused` = paused in aria2

### 1.7 Timestamps

Every item tracks its full lifecycle:

| Timestamp | Set when |
|---|---|
| `created_at` | Item added to queue |
| `paused_at` | User or af-scheduler pauses |
| `resumed_at` | User resumes |
| `completed_at` | Download finishes successfully |
| `error_at` | Download fails |
| `cancelled_at` | User removes (item archived) |

Use these for:
- "Added 5 minutes ago" relative times
- Duration calculations (download time = completed_at - created_at)
- Activity timeline per item
