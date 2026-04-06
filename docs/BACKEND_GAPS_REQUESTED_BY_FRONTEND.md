# Backend Gaps Requested by Frontend

> **Ownership:** Authored and maintained by the **ariaflow-web** frontend agent.
> The backend agent should read this file at session start, fix open items,
> and move them to the Resolved section when done — but should NOT add or
> delete entries (that's the frontend's responsibility).
>
> **Single source of truth — no mirrors.**
>
> **Pairing rule:** Every open backend gap should have a paired frontend gap in
> `../ariaflow-web/FRONTEND_GAPS.md` marked `Blocked by: BG-N` (unless it's
> pure infrastructure with no user-visible counterpart — then `Blocks frontend gap: (none)`).

---

_No open gaps._

---

## Explicit non-requests (do not implement)

Decisions made to prevent re-proposal by future agents. None of these will
ever be filed as BG entries.

| Topic | Decision | Reason |
|-------|----------|--------|
| Per-interface RX/TX byte counters | **Do not add** | Ariaflow is a download manager, not a network monitor. Users have `htop`/`btop`/Activity Monitor for network stats. The existing per-download speed + aggregate sparkline + bandwidth probe already answer "how much is flowing" for this domain. |
| Interface enumeration via API | **Do not add** | Exposes network topology. The frontend already enumerates its own interfaces via `local_identity()` in `bonjour.py`. Remote clients don't need to see the backend's interfaces; they already have one working URL. |

---

Historical resolved entries are preserved in git history.

## Resolved

| ID | What | Blocks frontend gap | Resolution |
|----|------|---------------------|------------|
| BG-6 | Bonjour TXT records need hostname | FE-14 (skip self-discoveries) | Added `hostname=<short_hostname>` TXT record to `_ariaflow._tcp` registration |
| BG-7 | SSE push action log entries | FE-15 (drop /api/log poll) | `append_action_log()` now publishes `action_logged` SSE event |
| BG-8 | Merge /api/health into /api/status | FE-16 (drop _heroTimer) | `health` object added to `/api/status` response |
| BG-9 | Scheduler backoff when aria2 unreachable | (none — backend-internal) | Exponential backoff 2s→60s in `process_queue()` loop |

*(BG-1 through BG-5 cleaned 2026-04-06 — see git log for history)*
