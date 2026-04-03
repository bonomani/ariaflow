# Naming Conventions — ariaflow vs aria2

**Rule:** Variables and statuses derived from aria2 should keep names consistent with aria2's vocabulary. ariaflow-only concepts use their own naming.

## Status Names

| aria2 status | ariaflow status | Match? |
|---|---|---|
| `active` | `active` | OK |
| `waiting` | `waiting` | OK |
| `paused` | `paused` | OK |
| `complete` | `complete` | OK |
| `error` | `error` | OK |
| `removed` | `stopped` | **Divergence** — justified (see below) |

**ariaflow-only statuses** (no aria2 equivalent):

| Status | Purpose |
|---|---|
| `discovering` | Pre-submission mode detection |
| `queued` | Safety-net fallback when aria2 unreachable |
| `cancelled` | User-initiated removal (archived) |

**Why `stopped` ≠ `removed`:** ariaflow distinguishes `stopped` (system decided, e.g. scheduler shutdown, aria2 crash) from `cancelled` (user decided). aria2's single `removed` status doesn't carry this distinction.

## Field Names — aria2-Derived

Fields that store values directly from aria2's `tellStatus` response:

| aria2 field | ariaflow field | Match? | Notes |
|---|---|---|---|
| `gid` | `gid` | OK | |
| `downloadSpeed` | `downloadSpeed` | OK | Stored as-is (camelCase) |
| `completedLength` | `completedLength` | OK | Stored as-is (camelCase) |
| `totalLength` | `totalLength` | OK | Stored as-is (camelCase) |
| `files` | `files` | OK | Stored as-is |
| `errorCode` | `error_code` | **Renamed** | aria2 camelCase → ariaflow snake_case |
| `errorMessage` | `error_message` | **Renamed** | aria2 camelCase → ariaflow snake_case |
| `status` | `live_status` | **Renamed** | Raw aria2 status stored separately from mapped ariaflow status |

**Inconsistency:** `downloadSpeed`, `completedLength`, `totalLength` keep aria2's camelCase, but `errorCode` and `errorMessage` are converted to snake_case. Both conventions exist in the same item dict.

### Options to resolve

| Option | Change | Impact |
|---|---|---|
| **A: Keep camelCase for all aria2 fields** | Rename `error_code` → `errorCode`, `error_message` → `errorMessage` | 55 references. Consistent with `downloadSpeed` etc. Breaks Python convention. |
| **B: Convert all to snake_case** | Rename `downloadSpeed` → `download_speed`, `completedLength` → `completed_length`, `totalLength` → `total_length` | 30+ references. Consistent Python style. Breaks alignment with aria2. |
| **C: Keep as-is** | No change | Inconsistent but working. Two conventions coexist. |

**Recommendation:** Option A — keep aria2 field names as-is (camelCase) for all aria2-derived fields. This makes it obvious which fields come from aria2. ariaflow-only fields stay snake_case.

## Field Names — ariaflow-Only

These are ariaflow concepts with no aria2 equivalent. All use snake_case (Python convention):

| Field | Purpose |
|---|---|
| `id` | ariaflow item UUID |
| `url` | Primary download URL |
| `output` | Custom output filename |
| `mode` | Download mode (http, magnet, torrent, etc.) |
| `priority` | Scheduling order |
| `mirrors` | Additional mirror URLs |
| `torrent_data` / `metalink_data` | Base64 embedded data |
| `status` | Mapped ariaflow status (may differ from `live_status`) |
| `live_status` | Raw aria2 status |
| `session_id` / `session_history` | Session tracking |
| `post_action_rule` / `post_action` | Post-completion policy |
| `created_at` / `paused_at` / `resumed_at` / `completed_at` / `error_at` / `cancelled_at` | Lifecycle timestamps |
| `rpc_failures` | RPC failure counter |

## Function Names

All 36 `aria2_*` wrapper functions use `aria2_` + snake_case of the RPC method name. **No gaps.** See [ARIA2_RPC_WRAPPERS.md](./ARIA2_RPC_WRAPPERS.md).
