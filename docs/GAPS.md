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

Backend gaps reported by the frontend project (`ariaflow-web`) are tracked in:
- **`../ariaflow-web/BACKEND_GAPS.md`** — gaps the backend must fix
- **`../ariaflow-web/FRONTEND_GAPS.md`** — frontend-side gaps (some blocked by backend)

Current open backend gaps from frontend:

| ID | Gap | Impact | Status |
|---|---|---|---|
| BG-1 | SSE pushes rev-only, not full payload | Frontend must poll after every event | Planned (see PLAN.md) |
| BG-2 | No PATCH for declaration preferences | Read-modify-write race on concurrent updates | Planned (see PLAN.md) |

### BG-1: SSE pushes rev-only — detail

When state changes (item added, download done, pause, etc.), the backend sends via SSE:

```json
{"rev": 42, "server_version": "0.1.98"}
```

The frontend knows *something* changed but not *what*. It must then call `GET /api/status` to get the full state — one extra HTTP round-trip per event. With 10 items changing in 2 seconds, that's 10 SSE events + 10 GET requests.

**Fix:** Push the full status payload in the SSE event data. The frontend updates immediately without polling.

### BG-2: No PATCH for declaration preferences — detail

To change one preference (e.g. `max_simultaneous_downloads: 3`), the frontend must:

1. `GET /api/declaration` — fetch the entire declaration
2. Find and modify the preference in the list
3. `POST /api/declaration` — send the entire modified declaration back

If two users change different preferences simultaneously, the second POST overwrites the first user's change (read-modify-write race condition).

**Fix:** `PATCH /api/declaration/preferences` accepts `{"key": value}` and merges atomically server-side. No GET needed, no race.
