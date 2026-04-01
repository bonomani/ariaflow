# ariaflow — Feature Gap Analysis (Backend)

Reference: [webui-aria2](https://github.com/ziahamza/webui-aria2)

This document identifies backend API gaps in ariaflow that block or
support features identified in the frontend gap analysis.

For the full feature comparison and frontend-only items, see
`../ariaflow-web/GAPS.md`.

Each gap is tagged with where the work lives:
- **backend** — work in this repo (`ariaflow`)
- **both** — coordinated change across both repos

---

## 2. Queue Interaction

### 2.3 Per-item action API — backend

- **Current state**: ariaflow exposes global queue controls only:
  `POST /api/pause`, `POST /api/resume`, `POST /api/run`.
  No per-item granularity.
- **webui-aria2 equivalent**: direct aria2 RPC calls (`pause`, `remove`,
  `unpause`, `removeDownloadResult`) per GID.
- **Value**: high — the frontend cannot offer per-item controls without
  these endpoints.
- **Required endpoints**:
  - `POST /api/item/<id>/pause` — pause a single queued/active item.
    Must call `aria2.pause(gid)` if the item has a live GID, and update
    the queue item status to `paused`.
  - `POST /api/item/<id>/resume` — resume a paused item.
    Must call `aria2.unpause(gid)` and update status.
  - `POST /api/item/<id>/remove` — remove an item from the queue.
    If active, call `aria2.remove(gid)` first. Remove from `queue.json`.
  - `POST /api/item/<id>/retry` — re-enqueue a failed item.
    Reset status to `queued`, clear error fields, optionally assign a
    new session.
- **Implementation notes**:
  - Item `<id>` is the queue item `id` field (not the aria2 GID).
  - Each endpoint must invalidate the status cache.
  - Each endpoint must log an action entry to `actions.jsonl`.
  - Pause/resume must respect the existing `paused` state flag and not
    conflict with the global pause/resume flow.
- **Frontend dependency**: `../ariaflow-web/GAPS.md` §2.3 will add
  inline buttons once these endpoints exist.
- **Status**: implemented.

---

## 3. Download Features

### 3.1 Torrent / metalink file selection API — backend

- **Current state**: ariaflow queues URLs for HTTP download. No support
  for torrent/metalink metadata inspection or file selection.
- **webui-aria2 equivalent**: uses aria2's `getFiles(gid)` RPC to list
  files, then `changeOption(gid, {select-file: "1,3,5"})` to pick files.
- **Value**: medium — extends ariaflow beyond HTTP-only downloads.
- **Required work**:
  - Support `.torrent` and `.metalink` URLs in the add flow.
  - Pass `--pause-metadata=true` to aria2 for these types so metadata
    downloads pause automatically.
  - Add `GET /api/item/<id>/files` — returns the file list from
    `aria2.getFiles(gid)`.
  - Add `POST /api/item/<id>/files` — accepts `{ select: [1, 3, 5] }`
    and calls `aria2.changeOption(gid, {select-file: ...})`, then
    `aria2.unpause(gid)`.
- **Frontend dependency**: `../ariaflow-web/GAPS.md` §3.1 will add a
  file picker UI.
- **Status**: missing.

### 3.2 DirectURL / file serving — backend

- **Current state**: completed files sit in aria2's download directory.
  No API to list or serve them.
- **webui-aria2 equivalent**: user configures a separate HTTP server
  pointing to the download directory.
- **Value**: medium — enables browser-based file retrieval.
- **Options**:
  - **Option A**: add `GET /api/files` to list completed files and
    `GET /api/files/<name>` to stream them. Gated behind a config flag
    (`serve_downloads: true`).
  - **Option B**: document how to point a static file server (nginx,
    caddy, python -m http.server) at the download directory. Zero
    backend code.
- **Recommendation**: Option B for now (no code); Option A later if
  demand exists.
- **Frontend dependency**: `../ariaflow-web/GAPS.md` §3.2.
- **Status**: missing.

---

## 4. Configuration & Settings

### 4.1 aria2 global options proxy — backend

- **Current state**: ariaflow manages aria2 internally. aria2 options
  are set at startup via the aria2 config file. No runtime option API.
- **webui-aria2 equivalent**: `changeGlobalOption` and `changeOption`
  RPC calls to modify aria2 settings at runtime.
- **Value**: low-medium — ariaflow intentionally abstracts aria2.
  Exposing raw options may break engine invariants.
- **Recommended safe subset** (if implemented):
  - `max-concurrent-downloads`
  - `max-connection-per-server`
  - `split`
  - `min-split-size`
  - `max-overall-download-limit`
  - `max-download-limit`
  - `timeout`
  - `connect-timeout`
- **Required endpoint**: `POST /api/aria2/options` — accepts a dict of
  option key-value pairs. Validates against the safe subset. Calls
  `aria2.changeGlobalOption(...)`.
- **Safeguards**:
  - Reject unknown option keys.
  - Reject options that conflict with engine-managed settings
    (e.g., `dir`, `rpc-*`, `enable-rpc`).
  - Log the change to `actions.jsonl`.
- **Frontend dependency**: `../ariaflow-web/GAPS.md` §4.1.
- **Status**: missing (by design — implement only if demand exists).

---

## 5. Deployment

### 5.2 Docker image — both

- **Current state**: ariaflow is distributed via pip and Homebrew. No
  Docker image.
- **Value**: medium — simplifies NAS, Raspberry Pi, server deployment.
- **Scope**: create a `Dockerfile` in this repo (or a shared
  `docker/` directory) that:
  - Installs aria2, ariaflow, and ariaflow-web.
  - Exposes ports 8000 (backend) and 8001 (frontend).
  - Mounts a volume for the download directory and config.
  - Optionally provides an ARM variant for Raspberry Pi.
- **Status**: missing.

---

## Priority Summary

| # | Feature | Value | Blocks frontend | Status |
|---|---------|-------|-----------------|--------|
| 2.3 | Per-item action API | high | yes (§2.3) | implemented |
| 3.1 | Torrent file selection API | medium | yes (§3.1) | missing |
| 3.2 | DirectURL / file serving | medium | yes (§3.2) | missing |
| 5.2 | Docker image | medium | no | missing |
| 4.1 | aria2 options proxy | low-medium | yes (§4.1) | missing |

---

## Recommended Next Steps (backend)

1. **Per-item action API** (2.3) — highest value; unblocks the most
   requested frontend feature.
2. **DirectURL via documentation** (3.2, Option B) — zero code, just
   document the static-server approach.
3. **Docker image** (5.2) — medium effort, broadens deployment reach.
4. **Torrent file selection** (3.1) — only if torrent support is planned.
5. **aria2 options proxy** (4.1) — only if users request it.

For frontend-only items that need no backend change, see
`../ariaflow-web/GAPS.md`.
