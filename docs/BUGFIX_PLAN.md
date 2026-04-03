# Improvement Plan

**All planned work is complete.**

Completed: Phase A (defensive fixes), Phase B (hybrid queue migration), Phase B+ (priority delegation), Phase D (BGS docs), Refactor (core.py split into 7 modules).

---

## Evaluated and Declined

### C1: Remove `stopped` status

Evaluated: `stopped` (aria2 reports `removed`) could map to `cancelled` instead. But `stopped` = system decided vs `cancelled` = user decided — removing the distinction loses information. **Decision: keep.**

### C2: Rename `downloading` to `active`

Evaluated: matches aria2 vocabulary, but 42 code+test references to change and breaks the API contract for frontend consumers. **Decision: don't do — not worth a breaking change.**
