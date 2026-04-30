# Backend Gaps Requested by Frontend

> **Ownership:** Authored and maintained by the **ariaflow-dashboard** frontend agent.
> The backend agent should read this file at session start, fix open items,
> and move them to the Resolved section when done — but should NOT add or
> delete entries (that's the frontend's responsibility).
>
> **Single source of truth — no mirrors.**
>
> **Pairing rule:** Every open backend gap should have a paired frontend gap in
> `../ariaflow-dashboard/FRONTEND_GAPS.md` marked `Blocked by: BG-N` (unless it's
> pure infrastructure with no user-visible counterpart — then `Blocks frontend gap: (none)`).

## Open (3)

### BG-16: Stale `ariaflow-web` references after rename

`AGENTS.md`, `docs/GAPS.md`, `README.md`, and `src/ariaflow_server/webapp.py`
still reference `ariaflow-web` (old name). The frontend repo was renamed to
`ariaflow-dashboard` and the GitHub repo is now `bonomani/ariaflow-dashboard`.

**Desired:**
- `AGENTS.md:20-21` — update header and path from `ariaflow-web` to `ariaflow-dashboard`.
- `docs/GAPS.md:5` — update `../ariaflow-web/GAPS.md` reference.
- `README.md:135-141` — update `ariaflow-web` references.
- `src/ariaflow_server/webapp.py:384` — update error message.
- Create `AGENT.md` at repo root — short pointer to `AGENTS.md` (matching dashboard pattern).

**Blocks frontend gap:** (none — pure infrastructure).

**Priority:** medium.

### BG-17: AGENTS.md lacks gap governance rules

The server's `AGENTS.md` only says "check this file when starting work".
It doesn't define the expected structure, so server agents may create gaps
in the wrong format or miss open items buried below resolved entries.

**Desired:** Add to `AGENTS.md` (self-contained, no frontend reads needed):
1. Instruct the agent to read `docs/BACKEND_GAPS_REQUESTED_BY_FRONTEND.md`
   at session start — fix open items, move to Resolved table when done.
2. Document the file structure: `## Open (N)` heading with count,
   `_End of open gaps._` sentinel, `## Resolved` compact table.
3. The backend agent should NEVER read files in `../ariaflow-dashboard/`
   or any other sibling repo. All information it needs is in this file.

**Blocks frontend gap:** (none — pure infrastructure).

**Priority:** medium.

### BG-15: Backend discovery uses stale mDNS service type

`discovery.py` browses for `_ariaflow._tcp` but `bonjour.py` registers as
`_ariaflow-server._tcp` (changed in commit `bf09621`). The service types
diverged during the naming alignment. Peer discovery between backends is
broken — `/api/peers` returns no results.

**Desired:**
- `discovery.py` should browse `_ariaflow-server._tcp` (to find peer backends).
- Optionally also browse `_ariaflow-dashboard._tcp` (to discover dashboards).

**Files to fix:**
- `src/ariaflow_server/discovery.py` — all occurrences of `_ariaflow._tcp`
  in browse/resolve commands and regexes (lines ~46, 57, 70, 135, 195, 244).
  Replace with `_ariaflow-server._tcp`.

**Why this matters for the frontend:** The dashboard uses `/api/peers` as a
fallback for Bonjour discovery when local mDNS is unavailable (e.g. WSL
behind NAT, containers, VMs). With BG-15 unfixed, this fallback returns
nothing, so the dashboard can't discover any peers in those environments.

**Blocks frontend gap:** FE-22.

**Priority:** high.

---

_End of open gaps._

## Explicit non-requests (do not implement)

| Topic | Decision | Reason |
|-------|----------|--------|
| Per-interface RX/TX byte counters | **Do not add** | Ariaflow is a download manager, not a network monitor. |
| Interface enumeration via API | **Do not add** | Exposes network topology. Frontend already has `local_identity()`. |

## Resolved

| ID | Summary | Date |
|----|---------|------|
| BG-20 | `/api/lifecycle` reshape: hyphen keys, `result` wrapper, aria2 + aria2-launchd records, recognized `reason` enum | 2026-04-30 |
| BG-19 | `/api/status` populates `ariaflow-server: {reachable, pid, version, error}` | 2026-04-30 |
| BG-18 | Backend announces `_ariaflow-server._tcp` via mDNS at startup (--no-mdns to disable) | 2026-04-30 |
| BG-14 | `archivable_count` exposed on `/api/status` summary | 2026-04-09 |
| BG-13 | WSL detection + default download dir to Windows filesystem | 2026-04-09 |
| BG-12 | Removed unused `/api/sessions/new` endpoint | 2026-04-09 |
| BG-11 | Residual under-specified fields after BG-10 (frontend updated schemas) | 2026-04-08 |
| BG-1–10 | See git history | — |

Details for all resolved entries are preserved in git history.
