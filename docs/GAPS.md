# ariaflow — Feature Gap Analysis (Backend)

Reference: [webui-aria2](https://github.com/ziahamza/webui-aria2)

For frontend-only items, see `../ariaflow-web/GAPS.md`.

## Status Summary

| # | Feature | Value | Status |
|---|---|---|---|
| 2.3 | Per-item action API | high | done |
| 3.1 | Torrent/metalink file selection | medium | done |
| 3.2 | DirectURL / file serving | medium | deferred |
| 4.1 | aria2 global options proxy | low-medium | done (safe subset) |
| 5.2 | Docker image | medium | done |

## Implemented

### 2.3 Per-item action API

Per-item endpoints: `POST /api/downloads/<id>/pause`, `resume`, `remove`, `retry`. Each validates state, logs to `actions.jsonl`, and triggers SSE events.

### 3.1 Torrent/metalink file selection

Supports `.torrent`, `.metalink`, magnet URLs with `--pause-metadata=true`. File picker via `GET /api/downloads/<id>/files` and selection via `POST /api/downloads/<id>/files` with `{select: [1,3,5]}`.

### 4.1 aria2 global options proxy

`POST /api/aria2/change_global_option` with 3-tier safety: managed options (download/upload limits, seed) blocked from generic API, safe options (concurrency, split, timeout) allowed, unsafe options require `aria2_unsafe_options` preference. Logs changes.

### 5.2 Docker image

Dockerfile installs aria2 + ariaflow + ariaflow-web. Exposes ports 8000/8001. Volume mount for downloads/config.

## Remaining

### 3.2 DirectURL / file serving — deferred

Completed files sit in aria2's download directory with no API to serve them. **Recommendation:** document how to point a static file server (nginx, caddy) at the download directory (zero code). Add `GET /api/files` later if demand exists.

## Cross-project gaps

Backend gaps reported by the frontend are tracked in `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md`
(written by the frontend agent per the cross-repo boundary rules).

Current status:

| ID | Gap | Status |
|---|---|---|
| BG-1 | SSE pushes rev-only | Done (SSE now pushes full payload) |
| BG-2 | No PATCH for declaration preferences | Done (`PATCH /api/declaration/preferences` added) |
| BG-3 | openapi.yaml lacks response field schemas | Done (openapi_schemas.py + gen_openapi.py) |
| BG-4 | openapi.yaml info.version is hardcoded | Done (gen_openapi.py injects `__version__`) |
| BG-5 | Bonjour instance name should be the short hostname | Done (`bonjour.py` `_short_hostname` + `_instance_name`) |
| BG-6 | Bonjour TXT records need a `hostname` key | Done (`hostname=<short>` added to dns-sd/avahi cmds) |
| BG-7 | SSE push for action_log entries (drop `/api/log` polling) | Done (`append_action_log` publishes `action_logged` event) |
| BG-8 | Merge `/api/health` into `/api/status` (drop `_heroTimer` polling) | Done (`/api/status` carries a `health` object) |
| BG-9 | Scheduler backoff when aria2 unreachable | Done (exponential 2s→60s in `process_queue`) |
| BG-10 | Under-specified response schemas in openapi.yaml for `/api/declaration`, `/api/lifecycle`, `/api/log` | Open (low priority, see PLAN.md) |
