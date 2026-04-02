# TIC Oracle — Ariaflow

Profile: ariaflow-scheduler
TIC ref: tic@7cfba80
Test file: `tests/test_tic.py`

## Test Inventory

### Session lifecycle (ASM Axis 1)

| Test | Intent | Oracle | Trace Target |
|---|---|---|---|
| `test_enqueue_creates_queue_item` | Adding a URL opens a session and creates a queued job | item.status == "queued", session_started_at set, action log contains "add" with session_id | ASM: none→open, Job: →queued |
| `test_new_session_closes_previous_and_starts_fresh` | Starting a new session closes the prior one | new session_id != old, session_started_at set, session_closed_at is None | ASM: open→closed→open |

### Preflight / UIC gates (ASM Axis 4 + UIC)

| Test | Intent | Oracle | Trace Target |
|---|---|---|---|
| `test_preflight_emits_gate_results` | Preflight produces structured gate results | result contains "gates", "status", exit_code in {0,1}, no action_log leak | UIC: gate evaluation |
| `test_preflight_bootstraps_aria2_when_rpc_is_initially_unavailable` | Preflight recovers by starting aria2 when initially unreachable | aria2_available gate satisfied, ensure_daemon called once | ASM: daemon absent→available (recovery) |
| `test_auto_preflight_default_is_disabled` | Auto-preflight preference defaults to off | auto_preflight_on_run.value == False | UIC: preference default |
| `test_concurrency_default_is_sequential` | Default concurrency is 1 (sequential) | max_simultaneous_downloads.value == 1 | UIC: preference default, Coherence CR-6 |
| `test_duplicate_active_transfer_default_is_remove` | Duplicate transfer policy defaults to "remove" | duplicate_active_transfer_action.value == "remove" | UIC: preference default |

### Bandwidth probing

| Test | Intent | Oracle | Trace Target |
|---|---|---|---|
| `test_probe_fallback_reports_reason` | Probe fallback uses safe default when tool unavailable | source == "default", reason == "probe_unavailable", cap_bytes_per_sec == 250000 | UCC: observation/fallback |
| `test_probe_uses_machine_readable_networkquality_output` | Probe parses networkQuality JSON correctly | source == "networkquality", downlink_mbps == 80.0, cap_mbps == 64.0 | UCC: observation |
| `test_probe_timeout_without_parse_uses_default_floor` | Probe timeout with no parse falls back to default | source == "default", reason == "probe_timeout_no_parse", partial == True | UCC: observation/fallback |
| `test_should_probe_bandwidth_uses_interval` | Probe respects 180s interval | True when no prior probe, False at 100s, True at 181s | UCC: rate limiting |
| `test_apply_bandwidth_probe_reuses_recent_probe` | Recent probe result is reused without re-probing | probe_bandwidth not called, cap_mbps == 64.0 | UCC: caching |
| `test_apply_bandwidth_probe_refreshes_stale_probe` | Stale probe triggers fresh measurement and applies bandwidth | probe_bandwidth called, set_bandwidth called with 4000000 | UCC: observation refresh |

### Active transfer management

| Test | Intent | Oracle | Trace Target |
|---|---|---|---|
| `test_discover_active_transfer_prefers_state_gid` | Active transfer discovery uses state.active_gid first | gid == "gid-1", status == "active", percent == 10.0 | UCC: observation |
| `test_discover_active_transfer_recovers_url_from_queue` | Missing URL recovered from queue by gid match | url == recovered URL from queue item | ASM: recovery |
| `test_deduplicate_active_transfers_removes_less_advanced_duplicates_by_default` | Dedup keeps most-advanced transfer, removes others | kept contains "gid-keep", paused contains "gid-drop", action == "remove" | UIC: duplicate policy, Coherence CR-6 |

### Queue reconciliation

| Test | Intent | Oracle | Trace Target |
|---|---|---|---|
| `test_reconcile_live_queue_adopts_unmatched_active_job` | Unmatched live download is adopted into queue | changed == True, recovered == 1 | ASM: recovery, Job: →downloading |
| `test_reconcile_live_queue_updates_old_session_item_in_place` | Stale session item updated to match live state | changed == True, recovered == 1 | ASM: session transition |
| `test_reconcile_live_queue_collapses_duplicate_rows_for_same_live_download` | Duplicate queue rows for same URL collapsed to one | len(saved) == 1, gid == live gid, completedLength preserved | Job: dedup |

### Execution / UCC result semantics (ASM Axis 2 + 3)

| Test | Intent | Oracle | Trace Target |
|---|---|---|---|
| `test_process_queue_marks_completed_tracked_download_done` | Completed download transitions to "done" with post_action | result[0].status == "done", gid == "gid-1", post_action present | ASM: Job downloading→complete→done, Run running→idle |
| `test_process_queue_resumes_paused_tracked_download` | Paused tracked download is resumed and completes | unpause RPC called, result[0].status == "done" | ASM: Job paused→queued→downloading→done |
| `test_ucc_returns_structured_result` | run_ucc produces UCC-compliant structured output | result contains "result", "meta", result.observation, result.outcome | UCC: contract shape |

### Install / uninstall lifecycle

| Test | Intent | Oracle | Trace Target |
|---|---|---|---|
| `test_install_dry_run_is_describable` | Install dry-run returns UCC-shaped plan | meta.contract == "UCC", observation == "ok", outcome == "changed" | UCC: lifecycle |
| `test_install_dry_run_with_aria2_is_describable` | Install with aria2 includes launchd component | "aria2-launchd" in plan, reason == "install" | UCC: lifecycle |
| `test_lifecycle_reports_status_shape` | Status report covers all components with UCC shape | all 4 components present, meta.contract == "UCC" | UCC: observation |
| `test_lifecycle_status_includes_versions` | Status includes version strings in messages | version strings present in messages | UCC: observation |
| `test_networkquality_status_reports_availability_without_probe` | networkquality status check doesn't trigger probe | run not called, installed == True, usable == True | UCC: observation |
| `test_uninstall_dry_run_is_describable` | Uninstall dry-run returns UCC-shaped plan | meta.contract == "UCC", reason == "uninstall" | UCC: lifecycle |
| `test_uninstall_dry_run_with_aria2_is_describable` | Uninstall with aria2 includes launchd component | "aria2-launchd" in plan, reason == "uninstall" | UCC: lifecycle |

## Extended Test Inventory (330 tests total)

### Per-item actions (`tests/test_tic.py` — TicPerItemTests, 10 tests)

| Test Class | Intent | Trace Target |
|---|---|---|
| `test_pause_queue_item_*` (3) | Pause queued/downloading items, reject invalid state | ASM: Job queued→paused |
| `test_resume_queue_item_*` (2) | Resume paused items with/without gid | ASM: Job paused→queued/downloading |
| `test_remove_queue_item_*` (2) | Remove items, verify aria2 cleanup | ASM: Job →cancelled |
| `test_retry_queue_item_*` (2) | Retry error items, reject non-error | ASM: Job error→queued |
| `test_not_found_item` (1) | 404 on missing item | UCC: error semantics |

### Download modes (`tests/test_tic.py` — TicTorrentAndOptionsTests, 9 tests)

| Test Class | Intent | Trace Target |
|---|---|---|
| `test_metadata_url_detection` (1) | Detect torrent/metalink/magnet URLs | UCC: mode detection |
| `test_add_download_*` (2) | Torrent gets pause-metadata, HTTP does not | UCC: aria2 RPC dispatch |
| `test_get_item_files_*` (2) | List files, handle missing gid | UCC: file selection |
| `test_select_item_files_*` (1) | Select files calls changeOption + unpause | UCC: execution |
| `test_change_aria2_options_*` (3) | Safe/unsafe/empty options validation | UIC: policy enforcement |

### API integration (`tests/test_api.py`, 77 tests)

| Test Class | Tests | Trace Target |
|---|---|---|
| TestStatusEndpoint | 4 | UCC: observation |
| TestAddEndpoint | 8 | UCC: execution, UIC: dedup policy |
| TestPerItemActions | 16 | ASM: all Job transitions |
| TestFileSelection | 7 | UCC: torrent file selection |
| TestAria2Options | 7 | UIC: safe option enforcement |
| TestBandwidth | 6 | UCC: bandwidth observation |
| TestEngineControl | 7 | ASM: Run axis transitions |
| TestDeclaration | 4 | UIC: declaration CRUD |
| TestSession | 2 | ASM: Session axis |
| TestActionLog | 4 | UCC: audit trail |
| TestLifecycle | 2 | UCC: lifecycle |
| TestMetaEndpoints | 9 | UCC: API contract (schema, ETag, SSE) |
| TestErrorHandling | 5 | UCC: error semantics |
| TestUCC | 1 | UCC: structured result |

### API coverage (`tests/test_api_coverage.py`, 52 tests)

| Test Class | Tests | Trace Target |
|---|---|---|
| TestGetEndpoints | 15 | UCC: every GET endpoint has correct shape |
| TestPostEndpoints | 22 | UCC: every POST endpoint accepts/rejects correctly |
| TestCrossCutting | 15 | UCC: schema version, request ID, ETag, CORS, revision |

### Cross-checks (`tests/test_cross_check.py`, 51 tests)

| Test Class | Tests | Trace Target |
|---|---|---|
| TestAddReflectedInStatus | 6 | UCC: observation consistency |
| TestPauseReflectedInStatus | 4 | ASM: Job state → status consistency |
| TestResumeReflectedInStatus | 3 | ASM: Job state → status consistency |
| TestRemoveReflectedInStatus | 2 | ASM: Job →cancelled → status consistency |
| TestRetryReflectedInStatus | 4 | ASM: Job error→queued → status consistency |
| TestDeclarationRoundtrip | 6 | UIC: declaration persistence |
| TestProbeReflectedInBandwidth | 1 | UCC: bandwidth observation |
| TestSessionReflectedInStatus | 1 | ASM: Session axis |
| TestRunReflectedInStatus | 2 | ASM: Run axis |
| TestFileSelectReflectedInStatus | 1 | UCC: file select → downloading |
| TestLogEntryDetails | 4 | UCC: audit trail detail fields |
| TestMultiStepChains | 4 | ASM: multi-axis transition sequences |
| TestMutationsLoggedInActionLog | 8 | UCC: all mutations logged |
| TestMutationsIncrementRevision | 5 | UCC: revision counter |

### End-to-end scenarios (`tests/test_scenarios.py`, 16 tests)

| Scenario | Trace Target |
|---|---|
| Normal download lifecycle | ASM: full Session→Run→Job lifecycle |
| Pause/resume/cancel | ASM: Job axis transitions |
| Error handling and retry | ASM: Job error→queued recovery |
| Session management | ASM: Session axis lifecycle |
| Bandwidth probe and config | UCC: bandwidth observation + UIC config |
| Torrent file selection | UCC: file selection workflow |
| aria2 options management | UIC: safe option policy |
| Preflight blocks start | UIC: gate enforcement (409) |
| Duplicate URL handling | UIC: dedup policy |
| Frontend consistency (ETag) | UCC: caching + schema version |
| SSE real-time events | UCC: event push |
| Lifecycle install/uninstall | UCC: lifecycle |
| Declaration roundtrip | UIC: persistence |
| Concurrent operations | UCC: thread safety |

### Regression tests (`tests/test_regressions.py`, 29 tests)

| Test | Bug prevented | Trace Target |
|---|---|---|
| `test_regression_recovered_item_gets_current_session_id` | Session isolation | ASM: recovery |
| `test_regression_rpc_watchdog_marks_error_after_failures` | Infinite loop | ASM: Coherence CR-4 |
| `test_regression_dedup_default_is_remove` | Policy mismatch | UIC: preference |
| `test_regression_cleanup_no_false_positive_change` | Unnecessary writes | UCC: idempotency |
| `test_regression_aria_rpc_raises_on_error_response` | Silent RPC failure | UCC: error semantics |
| `test_regression_storage_lock_closes_handle_on_flock_failure` | Resource leak | UCC: safety |
| `test_regression_probe_state_persisted` | Lost probe timing | UCC: observation |
| `test_regression_per_item_pause_releases_lock_before_rpc` | Lock contention | UCC: concurrency |
| `test_regression_state_revision_increments` | Stale frontend | UCC: revision |
| `test_regression_paused_cleared_on_queue_complete` | Permanent pause | ASM: Run axis |
| `test_regression_ensure_daemon_raises_on_failed_start` | Silent daemon failure | ASM: Daemon axis |
| `test_regression_retry_clears_recovery_fields` | Stale recovery metadata | ASM: recovery |
| `test_regression_mirror_urls_deduplicated` | Duplicate mirrors | UCC: execution |
| Security input validation (13) | XSS, injection, edge cases | UCC: input boundary |

### CLI tests (`tests/test_cli.py`, 25 tests)

| Test Class | Tests | Trace Target |
|---|---|---|
| TestCliParser | 15 | UCC: CLI contract (all subcommands parse correctly) |
| TestCliExecution | 10 | UCC: CLI execution (add, status, preflight, ucc, install, lifecycle) |

### Queue scheduler (`tests/scheduler/test_queue_scheduler.py`, 7 tests)

| Test | Trace Target |
|---|---|
| Cleanup collapses duplicates (2) | UCC: queue integrity |
| Normalize stale live_status (1) | ASM: Job state normalization |
| Process queue slot limits (2) | ASM: Coherence CR-6 |
| Process queue paused state (1) | ASM: Run axis |
| Startup cleanup before reconcile (1) | UCC: execution order |

## Coverage Summary

| Trace Target | Tests |
|---|---|
| ASM: Session axis | 12 |
| ASM: Run axis | 16 |
| ASM: Job axis (all transitions) | 62 |
| ASM: Daemon axis (recovery) | 4 |
| ASM: Coherence rules | 8 |
| ASM: Multi-axis sequences | 20 |
| UIC: gates / preferences | 18 |
| UIC: declaration CRUD | 10 |
| UIC: policy enforcement | 12 |
| UCC: execution results | 30 |
| UCC: observation consistency | 25 |
| UCC: error semantics | 15 |
| UCC: API contract shape | 52 |
| UCC: audit trail | 12 |
| UCC: lifecycle | 10 |
| UCC: concurrency / safety | 14 |
| UCC: input boundary (security) | 13 |
| UCC: CLI contract | 25 |
| **Total** | **330** |
