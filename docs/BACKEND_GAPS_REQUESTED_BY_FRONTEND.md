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

## Resolved

| ID | What | Blocks frontend gap | Resolution |
|----|------|---------------------|------------|
| BG-1 | SSE pushed rev-only | FE-7 (poll after each event) | SSE now pushes full payload (items, state, summary) |
| BG-2 | No PATCH for preferences | FE-8 (GET→merge→POST race) | `PATCH /api/declaration/preferences` added |
| BG-3 | openapi.yaml lacks response field schemas | (none — infrastructure; now consumed by frontend `TestBackendFieldCoverage` auto-discovery) | `openapi_schemas.py` + `gen_openapi.py` emit explicit `properties` per endpoint |
| BG-4 | openapi.yaml `info.version` stale | (none — spec hygiene) | `gen_openapi.py` now injects `__version__` into `info.version` on every regeneration |
