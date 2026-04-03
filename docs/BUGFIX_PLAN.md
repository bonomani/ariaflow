# Improvement Plan — Remaining Work

**Completed:** Phase A (defensive fixes), Phase B (hybrid queue migration), Phase B+ (priority delegation), Phase D (BGS docs), Refactor (core.py split).

---

## Phase C — Cleanup (optional, not committed)

### C1: Consider removing `stopped` status

`stopped` only occurs when aria2 reports `removed`. Could map to `cancelled` instead. Would reduce states from 9 to 8.

### C2: Consider renaming `downloading` to `active`

Matches aria2 vocabulary. Breaking API change — needs versioning.
