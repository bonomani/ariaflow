# Backend Gaps Requested by Frontend

> **Ownership:** Authored and maintained by the **ariaflow-web** frontend agent.
> The backend agent should read this file at session start, fix open items,
> and move them to the Resolved section when done — but should NOT add or
> delete entries (that's the frontend's responsibility).
>
> **Single source of truth — no mirrors.**
>
> **Note to backend agent:** This file was renamed from `BACKEND_GAPS.md` on
> 2026-04-06. Please update any references in the backend repo (CLAUDE.md,
> docs/GAPS.md, etc.) to the new filename.

---

_No open gaps._

## Resolved

| ID | What | Resolution |
|----|------|------------|
| BG-1 | SSE pushed rev-only | SSE now pushes full payload (items, state, summary) |
| BG-2 | No PATCH for preferences | `PATCH /api/declaration/preferences` added |
| BG-3 | openapi.yaml lacks response field schemas | `openapi_schemas.py` + `gen_openapi.py` emit explicit `properties` per endpoint |
