# Codebase Audit — ariaflow

Generated: 2026-04-03. Basis: 385 tests, 9 modules, 5226 source lines.

---

## Summary by Category

| # | Category | Score | Critical Findings | Total Effort |
|---|---|---|---|---|
| 1 | Correctness | Good | 6 silent exceptions, 1 logic bug | 8h |
| 2 | Test coverage | Excellent | 17 public functions lack direct tests, 1 dead function | 6h |
| 3 | Naming & readability | Excellent | 0 violations, 100% type annotations | 0h |
| 4 | Structure & modularity | Excellent | Already split into 9 modules | 0h |
| 5 | API consistency | Good | Inconsistent error format, missing `ok` on GET | 4h |
| 6 | Observability | Fair | No health check, silent exceptions, no log levels | 7h |
| 7 | Performance | Fair | N sequential RPC calls per tick, N+1 load_queue | 5h |
| 8 | Security | Fair | No URL validation, CORS *, no rate limiting, output path traversal | 10h |
| 9 | Documentation | Good | TIC oracle stale names, OpenAPI version out of sync | 5h |
| 10 | Developer experience | Fair | No Makefile, no pre-commit, CI macOS only, no CONTRIBUTING.md | 14h |

**Total estimated effort: ~59 hours**

---

## Findings Ordered by Priority

### P1 — Security (fix first, prevents exploitation)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 8.2 | No URL validation on add (SSRF, file://) | HIGH | webapp.py:122 | 20 lines |
| 8.9 | No output path validation (path traversal) | HIGH | webapp.py:129 | 20 lines |
| 8.10 | No mirror URL validation | HIGH | webapp.py:135 | 15 lines |
| 8.8 | aria2 options not filtered (already done in aria2_change_options but bypassed in webapp) | MEDIUM | webapp.py:1122 | 10 lines |
| 8.1 | CORS `*` on all endpoints | MEDIUM | webapp.py:multiple | 15 lines |
| 8.5 | No rate limiting | MEDIUM | webapp.py:all | 30 lines |
| 8.7 | Exception messages leaked in responses | LOW | webapp.py:multiple | 10 lines |
| 8.6 | Item ID not validated as UUID | LOW | webapp.py:700 | 5 lines |

### P2 — Performance (highest user-visible impact)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 7.1 | N sequential RPC calls in _poll_tracked_jobs — use aria2_multicall | HIGH | scheduler.py:186 | 2h |
| 7.2 | load_queue() called 36 times per cycle (N+1 disk I/O) | MEDIUM | multiple | 3h |

### P3 — API consistency (prevents client bugs)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 5.1 | Inconsistent error format (some use _error_payload, some inline dicts) | MEDIUM | webapp.py:multiple | 20 lines |
| 5.2 | GET endpoints missing `ok` field | MEDIUM | webapp.py:multiple | 25 lines |
| 5.3 | Wrong status code for ui_not_served (404 should be 400) | LOW | webapp.py:544 | 2 lines |

### P4 — Correctness (silent failures)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 1.2 | cleanup_queue_state failure swallowed | MEDIUM | webapp.py:457 | 8 lines |
| 1.4 | discover_active_transfer failure swallowed | MEDIUM | transfers.py:79 | 8 lines |
| 1.1 | _run_tests exception opaque | MEDIUM | webapp.py:398 | 5 lines |
| 1.3 | Bandwidth cap application failure swallowed | LOW | bandwidth.py:148 | 10 lines |
| 1.6 | Duplicate "complete" in session_stats tuple | LOW | state.py:288 | 3 lines |

### P5 — Observability (enables debugging)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 6.3 | No /api/health endpoint | MEDIUM | webapp.py | 1h |
| 6.4 | Silent exceptions lose traceback context | MEDIUM | scheduler.py:multiple | 2h |
| 6.5 | Request ID not propagated to action log | LOW | webapp.py/state.py | 1h |

### P6 — Test coverage (prevents regressions)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 2.1 | 17 public functions lack direct unit tests | MEDIUM | state.py, queue_ops.py | 6h |
| 2.2 | format_bytes is dead code | LOW | queue_ops.py:617 | 5 min |

### P7 — Documentation (accuracy)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 9.2 | TIC oracle uses old status names (downloading/done) | MEDIUM | tic-oracle.md | 2h |
| 9.3 | OpenAPI spec version out of sync (0.1.38 vs 0.1.95) | MEDIUM | openapi.yaml | 1h |
| 9.4 | No advanced usage examples | LOW | docs/ | 3h |

### P8 — Developer experience (onboarding speed)

| ID | Finding | Severity | File | Effort |
|---|---|---|---|---|
| 10.3 | CI only runs on macOS | MEDIUM | .github/workflows | 4h |
| 10.4 | No CONTRIBUTING.md | MEDIUM | root | 2h |
| 10.1 | No Makefile | LOW | root | 2h |
| 10.2 | No pre-commit hooks | LOW | root | 2h |
| 10.6 | No dev setup guide | LOW | docs/ | 3h |

---

## What's Already Excellent (no work needed)

- **Category 3 (Naming):** 0 violations, 11 automated naming tests, 100% type annotations
- **Category 4 (Structure):** 9 focused modules, no file > 1200 lines, clear separation of concerns
- **Governance:** BGS-State-Modeled-Governed-Verified with full evidence chain
- **RPC coverage:** All 36 aria2 methods wrapped with 1:1 naming
- **Hybrid queue model:** 6 design principles documented and implemented

---

## Recommended Execution Order

```
Phase 1: Security hardening (P1)          ~10h
  → URL/path validation, CORS, rate limit, error masking

Phase 2: Performance (P2)                  ~5h
  → multicall batching, load_queue caching

Phase 3: API consistency (P3)              ~4h
  → standardize error format, add ok field

Phase 4: Correctness (P4)                  ~4h
  → replace silent exceptions with logging

Phase 5: Observability (P5)                ~4h
  → health endpoint, exception context, request ID

Phase 6: Test coverage (P6)                ~6h
  → unit tests for untested functions, remove dead code

Phase 7: Documentation (P7)               ~5h
  → TIC oracle, OpenAPI version, examples

Phase 8: Developer experience (P8)        ~14h
  → CI matrix, CONTRIBUTING.md, Makefile, pre-commit
```
