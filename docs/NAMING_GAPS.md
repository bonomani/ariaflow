# Naming Conventions — ariaflow

**Project rule:** All ariaflow variables, fields, and statuses use **snake_case**, including those derived from aria2. aria2's camelCase names are translated at the boundary (when reading from or writing to aria2 RPC responses).

## Status Names

All status values use lowercase, matching aria2 where possible:

| aria2 status | ariaflow status | Notes |
|---|---|---|
| `active` | `active` | Direct match |
| `waiting` | `waiting` | Direct match |
| `paused` | `paused` | Direct match |
| `complete` | `complete` | Direct match |
| `error` | `error` | Direct match |
| `removed` | `stopped` | Divergence — ariaflow distinguishes `stopped` (system) from `cancelled` (user) |

ariaflow-only statuses (no aria2 equivalent): `discovering`, `queued`, `cancelled`.

## Field Names

### Translation boundary

aria2 returns camelCase fields. ariaflow translates them to snake_case at the boundary (`_apply_transfer_fields` in `scheduler.py`):

| aria2 field (camelCase) | ariaflow field (snake_case) | Where translated |
|---|---|---|
| `downloadSpeed` | `download_speed` | `_apply_transfer_fields()` |
| `completedLength` | `completed_length` | `_apply_transfer_fields()` |
| `totalLength` | `total_length` | `_apply_transfer_fields()` |
| `errorCode` | `error_code` | `_poll_tracked_jobs()` |
| `errorMessage` | `error_message` | `_poll_tracked_jobs()` |
| `gid` | `gid` | No translation needed (already lowercase) |
| `status` | `live_status` | Stored separately from mapped ariaflow status |
| `files` | `files` | No translation needed |

### ariaflow-only fields

All use snake_case (Python convention):

`id`, `url`, `output`, `mode`, `priority`, `mirrors`, `torrent_data`, `metalink_data`, `status`, `live_status`, `session_id`, `session_history`, `recovery_session_id`, `recovered_at`, `post_action_rule`, `post_action`, `created_at`, `paused_at`, `resumed_at`, `completed_at`, `error_at`, `removed_at`, `cancelled_at`, `rpc_failures`.

## Function Names

All 36 `aria2_*` wrapper functions use `aria2_` + snake_case of the RPC method name:

| Pattern | Example |
|---|---|
| `aria2.methodName` → `aria2_method_name` | `aria2.addUri` → `aria2_add_uri` |
| `aria2.tellStatus` → `aria2_tell_status` | |
| `system.multicall` → `aria2_multicall` | |

Full reference: [ARIA2_RPC_WRAPPERS.md](./ARIA2_RPC_WRAPPERS.md).

## No gaps remain

All naming is consistent. The camelCase → snake_case translation happens at the aria2 RPC boundary. Everything stored in `queue.json` and returned by the REST API uses snake_case.
