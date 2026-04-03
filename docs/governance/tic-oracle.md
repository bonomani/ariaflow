# TIC Oracle — Ariaflow

Profile: ariaflow-scheduler
TIC ref: tic@7cfba80
Generated: 2026-04-03
Test runner: `python -m pytest tests/ --collect-only -q`

## Test Inventory — All 374 Tests

---

### `tests/test_tic.py` — TicAriaFlowTests (32 tests)

Core scheduler, state machine, and UCC contract tests.

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 1 | `test_enqueue_creates_queue_item` | Adding a URL opens a session and creates a queued job | item.status == "queued", session_started_at set, action log contains "add" with session_id | ASM: none→open, Job: →queued |
| 2 | `test_new_session_closes_previous_and_starts_fresh` | Starting a new session closes the prior one | new session_id != old, session_started_at set, session_closed_at is None | ASM: open→closed→open |
| 3 | `test_enqueue_reuses_duplicate_url` | Duplicate URL returns existing item, logs "duplicate_url" | first.id == second.id, log entry has reason "duplicate_url", outcome "unchanged" | UIC: dedup policy |
| 4 | `test_preflight_emits_gate_results` | Preflight produces structured gate results | result contains "gates", "status", exit_code in {0,1}, no action_log leak | UIC: gate evaluation |
| 5 | `test_preflight_bootstraps_aria2_when_rpc_is_initially_unavailable` | Preflight recovers by starting aria2 when initially unreachable | aria2_available gate satisfied, ensure_daemon called once | ASM: daemon absent→available (recovery) |
| 6 | `test_auto_preflight_default_is_disabled` | Auto-preflight preference defaults to off | auto_preflight_on_run.value == False | UIC: preference default |
| 7 | `test_concurrency_default_is_sequential` | Default concurrency is 1 (sequential) | max_simultaneous_downloads.value == 1 | UIC: preference default, Coherence CR-6 |
| 8 | `test_duplicate_active_transfer_default_is_remove` | Duplicate transfer policy defaults to "remove" | duplicate_active_transfer_action.value == "remove" | UIC: preference default |
| 9 | `test_probe_fallback_reports_reason` | Probe fallback uses safe default when tool unavailable | source == "default", reason == "probe_unavailable", cap_bytes_per_sec == 250000 | UCC: observation/fallback |
| 10 | `test_probe_uses_machine_readable_networkquality_output` | Probe parses networkQuality JSON correctly | source == "networkquality", downlink_mbps == 80.0, cap_mbps == 64.0 | UCC: observation |
| 11 | `test_probe_timeout_without_parse_uses_default_floor` | Probe timeout with no parse falls back to default | source == "default", reason == "probe_timeout_no_parse", partial == True | UCC: observation/fallback |
| 12 | `test_should_probe_bandwidth_uses_interval` | Probe respects 180s interval | True when no prior probe, False at 100s, True at 181s | UCC: rate limiting |
| 13 | `test_apply_bandwidth_probe_reuses_recent_probe` | Recent probe result is reused without re-probing | probe_bandwidth not called, cap_mbps == 64.0 | UCC: caching |
| 14 | `test_apply_bandwidth_probe_refreshes_stale_probe` | Stale probe triggers fresh measurement and applies bandwidth | probe_bandwidth called, set_bandwidth called with 4000000 | UCC: observation refresh |
| 15 | `test_discover_active_transfer_prefers_state_gid` | Active transfer discovery uses state.active_gid first | gid == "gid-1", status == "active", percent == 10.0 | UCC: observation |
| 16 | `test_discover_active_transfer_recovers_url_from_queue` | Missing URL recovered from queue by gid match | url == recovered URL from queue item | ASM: recovery |
| 17 | `test_reconcile_promotes_paused_item_to_downloading_when_live_active` | Paused item promoted to downloading when aria2 reports active | saved[0].status == "downloading" | ASM: Job paused→downloading |
| 18 | `test_reconcile_live_queue_adopts_unmatched_active_job` | Unmatched live download is adopted into queue | changed == True, recovered == 1 | ASM: recovery, Job: →downloading |
| 19 | `test_reconcile_live_queue_updates_old_session_item_in_place` | Stale session item updated to match live state | changed == True, recovered == 1 | ASM: session transition |
| 20 | `test_reconcile_live_queue_collapses_duplicate_rows_for_same_live_download` | Duplicate queue rows for same URL collapsed to one | len(saved) == 1, gid == live gid, completedLength preserved | Job: dedup |
| 21 | `test_deduplicate_active_transfers_removes_less_advanced_duplicates_by_default` | Dedup keeps most-advanced transfer, removes others | kept contains "gid-keep", paused contains "gid-drop", action == "remove" | UIC: duplicate policy, Coherence CR-6 |
| 22 | `test_poll_marks_item_error_after_consecutive_rpc_failures` | After 5 consecutive RPC failures, item marked error | result[0].status == "error", error_code == "rpc_unreachable" | ASM: Coherence CR-4 |
| 23 | `test_process_queue_marks_completed_tracked_download_done` | Completed download transitions to "done" with post_action | result[0].status == "done", gid == "gid-1", post_action present | ASM: Job downloading→complete→done, Run running→idle |
| 24 | `test_process_queue_does_not_auto_resume_paused_items` | Paused items stay paused, user must explicitly resume | add_download not called, result[0].status == "paused" | ASM: Job paused stays paused |
| 25 | `test_ucc_returns_structured_result` | run_ucc produces UCC-compliant structured output | result contains "result", "meta", result.observation, result.outcome | UCC: contract shape |
| 26 | `test_install_dry_run_is_describable` | Install dry-run returns UCC-shaped plan | meta.contract == "UCC", observation == "ok", outcome == "changed" | UCC: lifecycle |
| 27 | `test_install_dry_run_with_aria2_is_describable` | Install with aria2 includes launchd component | "aria2-launchd" in plan, reason == "install" | UCC: lifecycle |
| 28 | `test_lifecycle_reports_status_shape` | Status report covers all components with UCC shape | all 4 components present, meta.contract == "UCC" | UCC: observation |
| 29 | `test_lifecycle_status_includes_versions` | Status includes version strings in messages | version strings present in messages | UCC: observation |
| 30 | `test_networkquality_status_reports_availability_without_probe` | networkquality status check doesn't trigger probe | run not called, installed == True, usable == True | UCC: observation |
| 31 | `test_uninstall_dry_run_is_describable` | Uninstall dry-run returns UCC-shaped plan | meta.contract == "UCC", reason == "uninstall" | UCC: lifecycle |
| 32 | `test_uninstall_dry_run_with_aria2_is_describable` | Uninstall with aria2 includes launchd component | "aria2-launchd" in plan, reason == "uninstall" | UCC: lifecycle |

### `tests/test_tic.py` — TicPerItemTests (10 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 33 | `test_pause_queue_item_sets_paused` | Pause a queued item sets status to paused | result.ok, item.status == "paused" | ASM: Job queued→paused |
| 34 | `test_pause_queue_item_calls_aria2_if_gid` | Pause a downloading item with gid calls aria2.pause | rpc called with aria2.pause, item.status == "paused" | ASM: Job downloading→paused |
| 35 | `test_pause_rejects_already_paused` | Pause an already paused item returns error | result.ok == False, error == "invalid_state" | UCC: error semantics |
| 36 | `test_resume_queue_item_from_paused` | Resume paused item without gid sets queued | result.ok, item.status == "queued" | ASM: Job paused→queued |
| 37 | `test_resume_queue_item_with_gid_calls_unpause` | Resume paused item with gid calls unpause, sets downloading | item.status == "downloading" | ASM: Job paused→downloading |
| 38 | `test_remove_queue_item_deletes_from_queue` | Remove queued item deletes it from queue | result.removed, queue is empty | ASM: Job →cancelled |
| 39 | `test_remove_active_item_calls_aria2_remove` | Remove downloading item calls aria2.remove | rpc called with aria2.remove, queue is empty | ASM: Job downloading→cancelled |
| 40 | `test_retry_queue_item_requeues_failed` | Retry error item requeues it, clears error fields | item.status == "queued", no error_code, no gid | ASM: Job error→queued |
| 41 | `test_retry_rejects_non_error_item` | Retry a queued item returns error | result.ok == False, error == "invalid_state" | UCC: error semantics |
| 42 | `test_not_found_item` | Action on nonexistent item returns not_found | result.ok == False, error == "not_found" | UCC: error semantics |

### `tests/test_tic.py` — TicTorrentAndOptionsTests (9 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 43 | `test_metadata_url_detection` | Detect torrent/metalink/magnet URLs, reject plain URLs | True for .torrent/.metalink/.meta4/magnet:, False for .zip/.gguf | UCC: mode detection |
| 44 | `test_add_download_sets_pause_metadata_for_torrent` | Torrent download gets pause-metadata=true option | options["pause-metadata"] == "true", gid returned | UCC: aria2 RPC dispatch |
| 45 | `test_add_download_no_pause_metadata_for_http` | HTTP download does not get pause-metadata | "pause-metadata" not in options | UCC: aria2 RPC dispatch |
| 46 | `test_get_item_files_returns_file_list` | List files for item with gid returns file list | result.ok, len(files) == 1 | UCC: file selection |
| 47 | `test_get_item_files_no_gid` | List files without gid returns error | result.ok == False, error == "no_gid" | UCC: error semantics |
| 48 | `test_select_item_files_calls_change_option_and_unpause` | Select files calls changeOption + unpause | rpc called with select-file and unpause | UCC: execution |
| 49 | `test_change_aria2_options_safe_subset` | Safe option accepted and applied via changeGlobalOption | result.ok, rpc called | UIC: policy enforcement |
| 50 | `test_change_aria2_options_rejects_unsafe` | Unsafe option (dir) rejected | result.ok == False, error == "rejected_options" | UIC: policy enforcement |
| 51 | `test_change_aria2_options_rejects_empty` | Empty options rejected | result.ok == False, error == "empty_options" | UIC: policy enforcement |

### `tests/test_tic.py` — TicOpenAPITests (1 test)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 52 | `test_openapi_spec_is_valid_yaml` | OpenAPI spec is valid YAML with required paths | openapi == "3.0.3", /api/status and /api/item paths present | UCC: API contract |

---

### `tests/test_api.py` — TestStatusEndpoint (4 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 53 | `test_status_returns_required_fields` | Status response has items, state, summary | code 200, all required keys present | UCC: API contract |
| 54 | `test_status_summary_counts_match_items` | Summary counts match actual item list | summary.queued == 2, summary.total == 2, len(items) == 2 | UCC: observation consistency |
| 55 | `test_status_includes_session_info` | Status includes session_id in state | state.session_id is not None | ASM: Session axis |
| 56 | `test_status_empty_queue` | Empty queue returns zero summary | summary.total == 0, items == [] | UCC: observation |

### `tests/test_api.py` — TestAddEndpoint (8 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 57 | `test_add_single_item` | Add one URL returns ok with item details | code 200, ok, count == 1, status == "queued" | UCC: execution |
| 58 | `test_add_multiple_items` | Add three URLs returns count 3 | count == 3, all URLs present | UCC: execution |
| 59 | `test_add_with_output_and_post_action` | Add with output and post_action_rule preserves them | output == "custom.bin", post_action_rule == "pending" | UCC: execution |
| 60 | `test_add_duplicate_url_returns_same_id` | Duplicate URL returns same item id | first.id == second.id | UIC: dedup policy |
| 61 | `test_add_empty_items_returns_400` | Empty items array returns 400 | code 400 | UCC: error semantics |
| 62 | `test_add_missing_items_returns_400` | Missing items key returns 400 | code 400 | UCC: error semantics |
| 63 | `test_add_invalid_json_returns_400` | Invalid JSON body returns 400 | code 400 | UCC: error semantics |
| 64 | `test_add_no_body_returns_400` | No body returns 400 | code 400 | UCC: error semantics |

### `tests/test_api.py` — TestPerItemActions (16 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 65 | `test_pause_queued_item` | Pause queued item via API | code 200, status == "paused" | ASM: Job queued→paused |
| 66 | `test_pause_already_paused_returns_400` | Pause already paused returns 400 | code 400, error == "invalid_state" | UCC: error semantics |
| 67 | `test_pause_done_item_returns_400` | Pause done item returns 400 | code 400, error == "invalid_state" | UCC: error semantics |
| 68 | `test_pause_nonexistent_returns_404` | Pause nonexistent item returns 404 | code 404, error == "not_found" | UCC: error semantics |
| 69 | `test_resume_paused_item_without_gid` | Resume paused item without gid sets queued | code 200, status == "queued" | ASM: Job paused→queued |
| 70 | `test_resume_paused_item_with_gid` | Resume paused item with gid sets downloading | code 200, status == "downloading" | ASM: Job paused→downloading |
| 71 | `test_resume_queued_item_returns_400` | Resume a queued item returns 400 | code 400, error == "invalid_state" | UCC: error semantics |
| 72 | `test_remove_queued_item` | Remove queued item | code 200, removed == True, queue empty | ASM: Job →cancelled |
| 73 | `test_remove_downloading_item_calls_aria2` | Remove downloading item calls aria2.remove | code 200, rpc called | ASM: Job downloading→cancelled |
| 74 | `test_remove_nonexistent_returns_404` | Remove nonexistent returns 404 | code 404 | UCC: error semantics |
| 75 | `test_double_remove_returns_404` | Second remove returns 404 | code 404 | UCC: error semantics |
| 76 | `test_retry_error_item` | Retry error item clears error fields | code 200, status == "queued", no error_code/gid | ASM: Job error→queued |
| 77 | `test_retry_failed_item` | Retry failed item sets queued | code 200, status == "queued" | ASM: Job failed→queued |
| 78 | `test_retry_stopped_item` | Retry stopped item sets queued | code 200, status == "queued" | ASM: Job stopped→queued |
| 79 | `test_retry_queued_item_returns_400` | Retry queued item returns 400 | code 400, error == "invalid_state" | UCC: error semantics |
| 80 | `test_retry_done_item_returns_400` | Retry done item returns 400 | code 400 | UCC: error semantics |
| 81 | `test_invalid_action_returns_400` | Invalid action name returns 400 | code 400, error == "invalid_action" | UCC: error semantics |

### `tests/test_api.py` — TestFileSelection (7 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 82 | `test_get_files_no_gid_returns_400` | Get files without gid returns 400 | code 400, error == "no_gid" | UCC: error semantics |
| 83 | `test_get_files_with_gid` | Get files with gid returns file list | code 200, len(files) == 2 | UCC: file selection |
| 84 | `test_get_files_nonexistent_returns_404` | Get files for nonexistent item returns 404 | code 404 | UCC: error semantics |
| 85 | `test_select_files` | Select files calls changeOption + unpause | code 200, selected == [1,3,5] | UCC: execution |
| 86 | `test_select_files_empty_returns_400` | Empty select list returns 400 | code 400 | UCC: error semantics |
| 87 | `test_select_files_missing_select_returns_400` | Missing select key returns 400 | code 400 | UCC: error semantics |
| 88 | `test_select_files_non_integer_returns_400` | Non-integer select values returns 400 | code 400 | UCC: error semantics |

### `tests/test_api.py` — TestAria2Options (7 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 89 | `test_safe_option_accepted` | Safe option accepted via API | code 200, ok, applied contains key | UIC: policy enforcement |
| 90 | `test_multiple_safe_options` | Multiple safe options applied | code 200, len(applied) == 3 | UIC: policy enforcement |
| 91 | `test_unsafe_option_rejected` | Unsafe option (dir) rejected | code 400, error == "rejected_options" | UIC: policy enforcement |
| 92 | `test_mixed_safe_unsafe_rejected` | Mix of safe+unsafe rejected | code 400, error == "rejected_options" | UIC: policy enforcement |
| 93 | `test_empty_options_rejected` | Empty options rejected | code 400 | UIC: policy enforcement |
| 94 | `test_non_object_payload_rejected` | Non-object payload rejected | code 400 | UCC: error semantics |
| 95 | `test_all_eight_safe_options` | All 8 safe options accepted at once | code 200, len(applied) == 8 | UIC: policy enforcement |

### `tests/test_api.py` — TestBandwidth (6 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 96 | `test_bandwidth_status_returns_config` | Bandwidth status has config with all keys | code 200, all config keys present | UCC: observation |
| 97 | `test_bandwidth_status_defaults` | Bandwidth defaults match declaration | down_free_percent == 20, up_free_percent == 50 | UIC: preference default |
| 98 | `test_bandwidth_status_includes_probe_info` | After probe, bandwidth status reflects probe data | downlink_mbps == 100.0, interface == "en0" | UCC: observation |
| 99 | `test_manual_probe` | Manual probe returns measured values | code 200, downlink_mbps == 50.0, source == "networkquality" | UCC: observation |
| 100 | `test_manual_probe_fallback` | Probe fallback when tool unavailable | code 200, source == "default", downlink_mbps is None | UCC: observation/fallback |
| 101 | `test_bandwidth_config_from_declaration` | Bandwidth config reflects declaration changes | down_free_percent == 30, down_use_percent == 0.7 | UIC: declaration→config |

### `tests/test_api.py` — TestEngineControl (7 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 102 | `test_run_start` | Start run via API | code 200, ok, action == "start" | ASM: Run axis |
| 103 | `test_run_stop` | Stop run via API | code 200, action == "stop" | ASM: Run axis |
| 104 | `test_run_invalid_action_returns_400` | Invalid run action returns 400 | code 400, error == "invalid_action" | UCC: error semantics |
| 105 | `test_run_missing_action_returns_400` | Missing action key returns 400 | code 400 | UCC: error semantics |
| 106 | `test_global_pause_resume` | Global pause then resume | code 200, paused/resumed keys present | ASM: Run axis |
| 107 | `test_preflight` | Preflight returns gate results | code 200, status == "pass", gates present | UIC: gate evaluation |
| 108 | `test_preflight_blocked_start` | Preflight fail blocks run start with 409 | code 409, error == "preflight_blocked" | UIC: gate enforcement |

### `tests/test_api.py` — TestDeclaration (4 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 109 | `test_get_declaration` | Get declaration returns UCC-shaped response | code 200, meta.contract == "UCC" | UIC: declaration CRUD |
| 110 | `test_get_options_is_alias` | /api/options is alias for /api/declaration | declaration == options (minus request_id) | UIC: declaration CRUD |
| 111 | `test_save_declaration` | Save declaration returns saved confirmation | code 200, saved == True | UIC: declaration CRUD |
| 112 | `test_save_declaration_roundtrip` | Save+reload preserves custom preference | test_pref in reloaded preference names | UIC: declaration persistence |

### `tests/test_api.py` — TestSession (2 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 113 | `test_new_session` | Create new session via API | code 200, new session_id != old | ASM: Session axis |
| 114 | `test_new_session_closes_previous` | New session logs session action | log contains "session" action | ASM: Session axis |

### `tests/test_api.py` — TestActionLog (4 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 115 | `test_log_default_limit` | Log endpoint returns items list | code 200, items is list | UCC: audit trail |
| 116 | `test_log_custom_limit` | Log with limit=3 returns at most 3 | len(items) <= 3 | UCC: audit trail |
| 117 | `test_log_entries_have_timestamps` | All log entries have timestamp | timestamp in every entry | UCC: audit trail |
| 118 | `test_log_records_add_action` | Add action is recorded in log | "add" in actions | UCC: audit trail |

### `tests/test_api.py` — TestLifecycle (2 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 119 | `test_lifecycle_status` | Lifecycle status has UCC-shaped components | code 200, meta.contract == "UCC" | UCC: lifecycle |
| 120 | `test_lifecycle_action_non_macos` | Lifecycle action on non-macOS returns 400 | code 400, error == "macos_only" | UCC: lifecycle |

### `tests/test_api.py` — TestUCC (1 test)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 121 | `test_ucc_returns_structured_result` | UCC endpoint returns meta + result with observation/outcome | code 200, meta and result present | UCC: contract shape |

### `tests/test_api.py` — TestMetaEndpoints (9 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 122 | `test_openapi_yaml` | OpenAPI YAML spec served correctly | code 200, contains "openapi:", yaml content-type | UCC: API contract |
| 123 | `test_swagger_ui` | Swagger UI HTML page served | code 200, contains "swagger-ui" | UCC: API contract |
| 124 | `test_cors_headers` | CORS allows all origins | Access-Control-Allow-Origin == "*" | UCC: API contract |
| 125 | `test_schema_version_in_response` | Schema version in response body | _schema == "2" | UCC: API contract |
| 126 | `test_request_id_in_response` | Unique request ID in each response | _request_id present, unique across requests | UCC: API contract |
| 127 | `test_schema_version_header` | Schema version in X-Schema-Version header | header == "2" | UCC: API contract |
| 128 | `test_etag_on_status` | ETag header on status, 304 on If-None-Match | ETag present, 304 on repeat | UCC: API contract (caching) |
| 129 | `test_revision_counter_in_status` | Revision counter is positive integer | _rev > 0 | UCC: API contract |
| 130 | `test_sse_endpoint_connects` | SSE endpoint sends connected event | text/event-stream, event: connected | UCC: API contract (SSE) |

### `tests/test_api.py` — TestErrorHandling (5 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 131 | `test_404_unknown_endpoint` | GET unknown endpoint returns 404 | code 404 | UCC: error semantics |
| 132 | `test_404_unknown_post_endpoint` | POST unknown endpoint returns 404 | code 404 | UCC: error semantics |
| 133 | `test_invalid_json_body` | Invalid JSON body returns 400 | code 400 | UCC: error semantics |
| 134 | `test_empty_post_body` | Empty POST body returns 400 | code 400 | UCC: error semantics |
| 135 | `test_concurrent_add_and_status` | 5 concurrent adds all succeed, status reflects all | all codes 200, total >= 5 | UCC: concurrency |

---

### `tests/test_api_coverage.py` — TestGetEndpoints (15 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 136 | `test_get_api_discovery` | GET /api returns endpoints, name, version | code 200, endpoints.GET/POST, name == "ariaflow" | UCC: API contract |
| 137 | `test_get_api_status` | GET /api/status has all required keys | code 200, items/state/summary/aria2/bandwidth/_rev/_schema/_request_id, ETag | UCC: API contract |
| 138 | `test_get_api_bandwidth` | GET /api/bandwidth has config with all bandwidth keys | code 200, all 7 config keys present | UCC: observation |
| 139 | `test_get_api_log_default` | GET /api/log returns items list | code 200, items is list | UCC: audit trail |
| 140 | `test_get_api_log_with_limit` | GET /api/log?limit=5 respects limit | code 200, len(items) <= 5 | UCC: audit trail |
| 141 | `test_get_api_declaration` | GET /api/declaration returns UCC-shaped declaration | code 200, meta.contract == "UCC", uic.gates/preferences | UIC: declaration CRUD |
| 142 | `test_get_api_options` | GET /api/options returns uic section | code 200, uic present | UIC: declaration CRUD |
| 143 | `test_get_api_lifecycle` | GET /api/lifecycle returns component statuses | code 200, ariaflow.meta.contract == "UCC" | UCC: lifecycle |
| 144 | `test_get_api_item_files_no_gid` | GET /api/item/{id}/files without gid returns 400 | code 400, error == "no_gid" | UCC: error semantics |
| 145 | `test_get_api_item_files_with_gid` | GET /api/item/{id}/files with gid returns file list | code 200, len(files) == 1 | UCC: file selection |
| 146 | `test_get_api_item_files_not_found` | GET /api/item/nonexistent/files returns 404 | code 404 | UCC: error semantics |
| 147 | `test_get_api_docs` | GET /api/docs returns Swagger UI HTML | code 200, text/html, swagger-ui | UCC: API contract |
| 148 | `test_get_api_openapi_yaml` | GET /api/openapi.yaml returns valid YAML | code 200, yaml content-type, openapi: | UCC: API contract |
| 149 | `test_get_api_tests` | GET /api/tests runs tests and returns results | code 200, ok, total == 1 | UCC: API contract |
| 150 | `test_get_api_events` | GET /api/events connects SSE with connected event | text/event-stream, event: connected | UCC: API contract (SSE) |

### `tests/test_api_coverage.py` — TestPostEndpoints (22 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 151 | `test_post_api_add` | POST /api/add succeeds | code 200, ok, count == 1 | UCC: execution |
| 152 | `test_post_api_add_invalid` | POST /api/add with empty items returns 400 | code 400 | UCC: error semantics |
| 153 | `test_post_api_run_start` | POST /api/run start returns ok | code 200, ok, action == "start" | ASM: Run axis |
| 154 | `test_post_api_run_stop` | POST /api/run stop returns ok | code 200, action == "stop" | ASM: Run axis |
| 155 | `test_post_api_run_invalid` | POST /api/run invalid action returns 400 | code 400 | UCC: error semantics |
| 156 | `test_post_api_preflight` | POST /api/preflight returns pass | code 200, status == "pass" | UIC: gate evaluation |
| 157 | `test_post_api_ucc` | POST /api/ucc returns structured result | code 200, meta + result present | UCC: contract shape |
| 158 | `test_post_api_pause` | POST /api/pause returns paused key | code 200, paused present | ASM: Run axis |
| 159 | `test_post_api_resume` | POST /api/resume returns resumed key | code 200, resumed present | ASM: Run axis |
| 160 | `test_post_api_session` | POST /api/session new returns ok | code 200, ok, session present | ASM: Session axis |
| 161 | `test_post_api_declaration` | POST /api/declaration saves successfully | code 200, saved == True | UIC: declaration CRUD |
| 162 | `test_post_api_bandwidth_probe` | POST /api/bandwidth/probe returns probe data | code 200, ok, downlink_mbps/uplink_mbps present | UCC: observation |
| 163 | `test_post_api_aria2_options_safe` | POST /api/aria2/options safe option accepted | code 200, ok | UIC: policy enforcement |
| 164 | `test_post_api_aria2_options_unsafe` | POST /api/aria2/options unsafe option rejected | code 400, error == "rejected_options" | UIC: policy enforcement |
| 165 | `test_post_api_item_pause` | POST /api/item/{id}/pause sets paused | code 200, status == "paused" | ASM: Job queued→paused |
| 166 | `test_post_api_item_resume` | POST /api/item/{id}/resume resumes | code 200, status in (queued, downloading) | ASM: Job paused→queued |
| 167 | `test_post_api_item_remove` | POST /api/item/{id}/remove removes | code 200, removed == True | ASM: Job →cancelled |
| 168 | `test_post_api_item_retry` | POST /api/item/{id}/retry requeues error item | code 200, status == "queued" | ASM: Job error→queued |
| 169 | `test_post_api_item_files_select` | POST /api/item/{id}/files selects files | code 200, selected == [1, 2] | UCC: execution |
| 170 | `test_post_api_item_files_select_invalid` | POST /api/item/{id}/files empty select returns 400 | code 400 | UCC: error semantics |
| 171 | `test_post_api_lifecycle_action_non_macos` | POST /api/lifecycle/action non-macOS returns 400 | code 400, error == "macos_only" | UCC: lifecycle |
| 172 | `test_post_api_lifecycle_action_install` | POST /api/lifecycle/action install succeeds | code 200, ok | UCC: lifecycle |

### `tests/test_api_coverage.py` — TestCrossCutting (15 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 173 | `test_schema_version_in_body` | _schema == "2" in response body | _schema == "2" | UCC: API contract |
| 174 | `test_schema_version_in_header` | X-Schema-Version header == "2" | header == "2" | UCC: API contract |
| 175 | `test_request_id_unique` | Request IDs are unique across calls | id1 != id2 | UCC: API contract |
| 176 | `test_request_id_in_header` | X-Request-Id header present | len > 0 | UCC: API contract |
| 177 | `test_etag_304` | ETag on status, 304 on If-None-Match | ETag present, 304 returned | UCC: API contract (caching) |
| 178 | `test_cors_allow_origin` | CORS Access-Control-Allow-Origin == "*" | header == "*" | UCC: API contract |
| 179 | `test_revision_increments` | Revision counter increments after mutation | rev2 >= rev1 | UCC: API contract |
| 180 | `test_get_404` | GET unknown endpoint returns 404 | code 404 | UCC: error semantics |
| 181 | `test_post_404` | POST unknown endpoint returns 404 | code 404 | UCC: error semantics |
| 182 | `test_invalid_json_body` | Invalid JSON body returns 400 | code 400, error == "invalid_json" | UCC: error semantics |
| 183 | `test_invalid_item_action` | Invalid item action returns 400 | code 400, error == "invalid_action" | UCC: error semantics |
| 184 | `test_item_not_found` | Nonexistent item returns 404 | code 404 | UCC: error semantics |
| 185 | `test_add_reflected_in_status` | Add reflected in status items | URL in status items | UCC: observation consistency |
| 186 | `test_remove_reflected_in_status` | Remove reflected in status items | item_id not in status items | UCC: observation consistency |
| 187 | `test_actions_logged` | Add action appears in log | "add" in log actions | UCC: audit trail |

---

### `tests/test_cross_check.py` — TestAddReflectedInStatus (6 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 188 | `test_added_item_appears_in_status` | Added item visible in status with correct url/status | item present, status == "queued" | UCC: observation consistency |
| 189 | `test_added_item_counted_in_summary` | Total increments by 1 after add | after.total == before.total + 1 | UCC: observation consistency |
| 190 | `test_added_item_creates_session` | Add creates session, session_id matches | status.state.session_id == added.session_id | ASM: Session axis |
| 191 | `test_add_multiple_all_in_status` | All 3 added items present in status | added_ids subset of status_ids | UCC: observation consistency |
| 192 | `test_add_with_output_reflected` | Output field preserved in status | item.output == "custom.bin" | UCC: observation consistency |
| 193 | `test_duplicate_add_same_id_in_status` | Duplicate add returns same id, only 1 item in status | first.id == second.id, len(matching) == 1 | UIC: dedup policy |

### `tests/test_cross_check.py` — TestPauseReflectedInStatus (4 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 194 | `test_paused_item_status_matches` | Paused item shows paused in status | item.status == "paused" | ASM: Job queued→paused |
| 195 | `test_paused_item_summary_counts` | Summary paused count > 0 after pause | summary.paused > 0 | UCC: observation consistency |
| 196 | `test_pause_preserves_url_and_id` | Pause preserves url and id | item.url == original, item.id == original | UCC: observation consistency |
| 197 | `test_pause_does_not_affect_other_items` | Pausing one item leaves others unchanged | other_item.status == "queued" | UCC: observation consistency |

### `tests/test_cross_check.py` — TestResumeReflectedInStatus (3 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 198 | `test_resumed_item_status_matches` | Resumed item status in status matches action response | status matches | ASM: Job paused→queued |
| 199 | `test_resume_clears_paused_summary` | Resume decreases paused count | paused_after < paused_before | UCC: observation consistency |
| 200 | `test_pause_resume_cycle_preserves_url` | Multiple pause/resume cycles preserve url | item.url == original | UCC: observation consistency |

### `tests/test_cross_check.py` — TestRemoveReflectedInStatus (2 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 201 | `test_removed_item_gone_from_status` | Removed item no longer in status items | item_id not in ids | ASM: Job →cancelled |
| 202 | `test_removed_item_reduces_total` | Total decreases by 1 after remove | after.total == before.total - 1 | UCC: observation consistency |

### `tests/test_cross_check.py` — TestRetryReflectedInStatus (4 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 203 | `test_retried_item_back_to_queued` | Retried error item shows queued in status | item.status == "queued", no error_code, no gid | ASM: Job error→queued |
| 204 | `test_retry_clears_error_message` | Retry clears error_message in status | item.error_message is None | UCC: observation consistency |
| 205 | `test_retry_preserves_url` | Retry preserves original URL | item.url == original | UCC: observation consistency |
| 206 | `test_retry_error_count_decreases` | Error count decreases after retry | err_after < err_before | UCC: observation consistency |

### `tests/test_cross_check.py` — TestDeclarationRoundtrip (6 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 207 | `test_saved_declaration_readable` | Save then reload preserves all preferences | saved_names == reloaded_names | UIC: declaration persistence |
| 208 | `test_bandwidth_config_reflects_declaration_change` | Bandwidth config reflects declaration preference change | down_free_percent == 40, down_use_percent == 0.6 | UIC: declaration→config |
| 209 | `test_options_alias_matches_declaration` | /api/options matches /api/declaration | decl == opts | UIC: declaration CRUD |
| 210 | `test_declaration_gate_change_reflected` | Custom gate persisted in declaration | "xc_test_gate" in gate_names | UIC: declaration persistence |
| 211 | `test_declaration_preference_value_change_reflected` | Preference value change persisted | max_simultaneous_downloads.value == 5 | UIC: declaration persistence |
| 212 | `test_all_bandwidth_prefs_in_declaration_and_config` | All bandwidth prefs in declaration, all config keys in bandwidth | expected subset of names, expected_config subset of keys | UIC: declaration persistence |

### `tests/test_cross_check.py` — TestProbeReflectedInBandwidth (1 test)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 213 | `test_manual_probe_reflected_in_bandwidth_status` | Manual probe results visible in bandwidth status | downlink_mbps, uplink_mbps, interface, caps match | UCC: observation consistency |

### `tests/test_cross_check.py` — TestSessionReflectedInStatus (1 test)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 214 | `test_new_session_reflected_in_status` | New session id reflected in status | status.state.session_id == new_id | ASM: Session axis |

### `tests/test_cross_check.py` — TestRunReflectedInStatus (2 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 215 | `test_run_start_sets_running` | Run start accepted, running key in state | state.running present | ASM: Run axis |
| 216 | `test_run_stop_clears_running` | Run stop clears running flag | state.running == False | ASM: Run axis |

### `tests/test_cross_check.py` — TestFileSelectReflectedInStatus (1 test)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 217 | `test_file_select_sets_downloading` | File selection sets item to downloading | item.status == "downloading" | UCC: execution |

### `tests/test_cross_check.py` — TestMutationsLoggedInActionLog (8 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 218 | `test_add_logged` | Add action recorded in log | "add" in actions | UCC: audit trail |
| 219 | `test_pause_logged` | Pause action recorded in log | "pause" in actions | UCC: audit trail |
| 220 | `test_resume_logged` | Resume action recorded in log | "resume" in actions | UCC: audit trail |
| 221 | `test_remove_logged` | Remove action recorded in log | "remove" in actions | UCC: audit trail |
| 222 | `test_retry_logged` | Retry action recorded in log | "retry" in actions | UCC: audit trail |
| 223 | `test_session_logged` | Session action recorded in log | "session" in actions | UCC: audit trail |
| 224 | `test_probe_logged` | Probe action recorded in log | "probe" in actions | UCC: audit trail |
| 225 | `test_run_logged` | Run action recorded in log | "run" in actions | UCC: audit trail |

### `tests/test_cross_check.py` — TestLogEntryDetails (4 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 226 | `test_add_log_contains_url` | Add log entry has session_id and timestamp | session_id and timestamp present | UCC: audit trail |
| 227 | `test_pause_log_contains_item_id` | Pause log entry has item_id in detail | detail.item_id == item_id | UCC: audit trail |
| 228 | `test_remove_log_contains_item_id` | Remove log entry has item_id in detail | detail.item_id == item_id | UCC: audit trail |
| 229 | `test_log_entries_ordered_by_time` | Log entries are time-ordered | timestamps == sorted(timestamps) | UCC: audit trail |

### `tests/test_cross_check.py` — TestMultiStepChains (4 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 230 | `test_add_pause_resume_remove_chain` | Full add→pause→resume→remove chain consistent with status | each step verified in status | ASM: multi-axis transitions |
| 231 | `test_error_retry_pause_chain` | error→retry→pause chain consistent | retry sets queued, pause sets paused | ASM: multi-axis transitions |
| 232 | `test_multiple_items_independent_state` | 4 items with different states are independent | paused, removed, queued, error all correct | ASM: multi-axis transitions |
| 233 | `test_session_change_does_not_affect_existing_items` | New session does not affect existing items | item still queued with original url | ASM: Session axis |

### `tests/test_cross_check.py` — TestMutationsIncrementRevision (5 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 234 | `test_add_increments_rev` | Add increments revision counter | rev_after > rev_before | UCC: revision |
| 235 | `test_session_increments_rev` | New session increments revision | rev_after > rev_before | UCC: revision |
| 236 | `test_pause_increments_rev` | Pause increments revision | rev_after > rev_before | UCC: revision |
| 237 | `test_remove_increments_rev` | Remove increments revision | rev_after > rev_before | UCC: revision |
| 238 | `test_retry_increments_rev` | Retry increments revision | rev_after > rev_before | UCC: revision |

---

### `tests/test_scenarios.py` (16 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 239 | `test_full_download_lifecycle` | Full workflow: preflight→add→start→complete→stop→log | 3 items done, log has add/preflight/run | ASM: full Session→Run→Job lifecycle |
| 240 | `test_pause_resume_remove_workflow` | Pause all, resume one, remove one, verify states | A queued, B gone, C paused | ASM: Job axis transitions |
| 241 | `test_error_retry_workflow` | Error items, retry one, remove other, reject invalid retry | 1 queued, 0 errors, retry-queued returns 400 | ASM: Job error→queued recovery |
| 242 | `test_session_lifecycle` | Add creates session, new session changes id, log records | session_2 != session_1, session actions logged | ASM: Session axis lifecycle |
| 243 | `test_bandwidth_config_and_probe` | Configure bandwidth prefs, run probe, verify caps | down_free_percent == 30, down_cap <= 70 | UCC: bandwidth observation + UIC config |
| 244 | `test_torrent_file_pick_workflow` | Add torrent, list files, select subset, verify downloading | 3 files listed, selected [1], status downloading | UCC: file selection workflow |
| 245 | `test_options_management` | Reject unsafe, apply safe options, verify logged | 400 on unsafe, 200 on safe, change_options logged | UIC: safe option policy |
| 246 | `test_preflight_blocks_start` | Auto-preflight fails, blocks run with 409 | code 409, error == "preflight_blocked", not running | UIC: gate enforcement |
| 247 | `test_duplicate_urls` | Add same URL twice returns same id, only 1 in queue | first_id == second_id, 1 matching item | UIC: dedup policy |
| 248 | `test_etag_caching_workflow` | ETag caching: 304 on same state, new ETag after mutation | 304 on repeat, etag2 != etag1 | UCC: caching |
| 249 | `test_schema_version_detection` | Schema version in body, header, and ariaflow section | all == "2" | UCC: API contract |
| 250 | `test_sse_receives_state_change` | SSE connected event, then state_changed on add | event: connected, event: state_changed with rev | UCC: event push |
| 251 | `test_lifecycle_check_and_action` | Check lifecycle, install, uninstall (mocked) | ariaflow/aria2/networkquality present, install ok | UCC: lifecycle |
| 252 | `test_declaration_custom_prefs` | Add/modify custom preference, verify persistence | custom_test_pref saved and modified correctly | UIC: declaration persistence |
| 253 | `test_concurrent_adds` | 10 concurrent add requests all succeed | all 200, total >= 10 | UCC: thread safety |
| 254 | `test_concurrent_pause_resume` | 5 concurrent pauses all succeed | all 200 | UCC: thread safety |

---

### `tests/test_regressions.py` — TestRegressions (16 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 255 | `test_regression_recovered_item_gets_current_session_id` | Recovered item gets current session_id, not old one | session_id == "new-session", recovery_session_id set | ASM: recovery |
| 256 | `test_regression_paused_item_promoted_via_merge_active_status` | Paused item promoted to downloading when live is active | saved[0].status == "downloading" | ASM: Job paused→downloading |
| 257 | `test_regression_rpc_watchdog_marks_error_after_failures` | After 5 RPC failures, item marked error (prevents infinite loop) | status == "error", error_code == "rpc_unreachable" | ASM: Coherence CR-4 |
| 258 | `test_regression_dedup_default_is_remove` | Dedup policy defaults to "remove" (not "pause") | action == "remove" | UIC: preference default |
| 259 | `test_regression_resume_sets_downloading_not_queued` | Resume sets "downloading" not "queued" (prevents re-add) | status == "downloading" for resumed item with gid | ASM: Job paused→downloading |
| 260 | `test_regression_action_log_rotation_exists` | Action log rotation constants exist (max 10000, keep 5000) | MAX == 10000, KEEP == 5000 | UCC: audit trail |
| 261 | `test_regression_cleanup_no_false_positive_change` | Cleanup with no duplicates reports changed=False | changed == False | UCC: idempotency |
| 262 | `test_regression_aria_rpc_raises_on_error_response` | aria_rpc raises RuntimeError on JSON-RPC error | RuntimeError raised, "bad" in message | UCC: error semantics |
| 263 | `test_regression_storage_lock_closes_handle_on_flock_failure` | File handle closed if flock() raises OSError | OSError raised, no resource leak | UCC: safety |
| 264 | `test_regression_probe_state_persisted` | Probe state persisted via save_state after probe | save_state called, last_bandwidth_probe in state | UCC: observation |
| 265 | `test_regression_per_item_pause_releases_lock_before_rpc` | RPC call made outside storage lock (no lock contention) | depth == 0 during rpc call | UCC: concurrency |
| 266 | `test_regression_state_revision_increments` | save_state increments _rev on every write | rev1 > rev0, rev2 > rev1 | UCC: revision |
| 267 | `test_regression_paused_cleared_on_queue_complete` | Paused flag cleared when queue completes | state.paused == False, state.running == False | ASM: Run axis |
| 268 | `test_regression_ensure_daemon_raises_on_failed_start` | ensure_aria_daemon raises on failed start | RuntimeError raised, "aria2c failed to start" | ASM: Daemon axis |
| 269 | `test_regression_retry_clears_recovery_fields` | Retry clears recovered, recovered_at, recovery_session_id | none of those fields in result item | ASM: recovery |
| 270 | `test_regression_mirror_urls_deduplicated` | Mirror URLs deduplicated before RPC call | len(uris) == 2, no duplicates | UCC: execution |

### `tests/test_regressions.py` — TestSecurityInputValidation (13 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 271 | `test_add_item_with_very_long_url` | Very long URL (10000 chars) accepted | item.url == url | UCC: input boundary |
| 272 | `test_add_item_with_special_chars_in_url` | URL with query params and fragment accepted | item.url == url | UCC: input boundary |
| 273 | `test_add_item_with_unicode_url` | Unicode URL accepted | item.url == url | UCC: input boundary |
| 274 | `test_aria2_options_rejects_rpc_options` | rpc-listen-port rejected as unsafe | ok == False, error == "rejected_options" | UCC: input boundary |
| 275 | `test_aria2_options_rejects_dir` | dir option rejected as unsafe | ok == False | UCC: input boundary |
| 276 | `test_aria2_options_rejects_conf_path` | conf-path option rejected as unsafe | ok == False | UCC: input boundary |
| 277 | `test_aria2_options_rejects_log` | log option rejected as unsafe | ok == False | UCC: input boundary |
| 278 | `test_metadata_url_detection_no_false_positives` | Plain URLs not detected as metadata | False for .bin, .html, .mp3 | UCC: input boundary |
| 279 | `test_metadata_url_detection_true_positives` | Metadata URLs correctly detected | True for .torrent, .TORRENT, .metalink, .meta4, magnet: | UCC: input boundary |
| 280 | `test_bandwidth_cap_with_zero_measured` | Zero measured bandwidth returns None | result is None | UCC: input boundary |
| 281 | `test_bandwidth_cap_with_none_measured` | None measured bandwidth returns None | result is None | UCC: input boundary |
| 282 | `test_bandwidth_cap_with_negative_measured` | Negative measured bandwidth returns None | result is None | UCC: input boundary |
| 283 | `test_bandwidth_cap_100_percent_free` | 100% free means 0 cap | result == 0.0 | UCC: input boundary |
| 284 | `test_bandwidth_cap_absolute_exceeds_measured` | Absolute free exceeding measured means 0 cap | result == 0.0 | UCC: input boundary |

---

### `tests/test_cli.py` — TestCliParser (15 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 285 | `test_add_subcommand` | Parse "add URL" command | command == "add", url set, output None | UCC: CLI contract |
| 286 | `test_add_with_options` | Parse "add URL --output --post-action-rule" | output == "custom.bin", post_action_rule == "delete" | UCC: CLI contract |
| 287 | `test_run_subcommand` | Parse "run" command | command == "run", port == 6800 | UCC: CLI contract |
| 288 | `test_run_with_port` | Parse "run --port 7800" | port == 7800 | UCC: CLI contract |
| 289 | `test_status_subcommand` | Parse "status" command | command == "status", json == False | UCC: CLI contract |
| 290 | `test_status_json` | Parse "status --json" | json == True | UCC: CLI contract |
| 291 | `test_preflight_subcommand` | Parse "preflight" command | command == "preflight" | UCC: CLI contract |
| 292 | `test_ucc_subcommand` | Parse "ucc" command | command == "ucc", port == 6800 | UCC: CLI contract |
| 293 | `test_serve_subcommand` | Parse "serve" command | command == "serve", host == "127.0.0.1", port == 8000 | UCC: CLI contract |
| 294 | `test_serve_with_options` | Parse "serve --host --port" | host == "0.0.0.0", port == 9000 | UCC: CLI contract |
| 295 | `test_install_subcommand` | Parse "install" command | command == "install", dry_run == False | UCC: CLI contract |
| 296 | `test_install_with_flags` | Parse "install --dry-run --with-aria2" | dry_run == True, with_aria2 == True | UCC: CLI contract |
| 297 | `test_uninstall_subcommand` | Parse "uninstall" command | command == "uninstall" | UCC: CLI contract |
| 298 | `test_lifecycle_subcommand` | Parse "lifecycle" command | command == "lifecycle" | UCC: CLI contract |
| 299 | `test_no_subcommand_fails` | No subcommand raises SystemExit | SystemExit raised | UCC: CLI contract |

### `tests/test_cli.py` — TestCliExecution (10 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 300 | `test_add_prints_queued` | "add" prints "Queued:" with URL | exit 0, "Queued:" and URL in stdout | UCC: CLI execution |
| 301 | `test_status_plain` | "status" prints plain text with item | exit 0, "queued" and URL in stdout | UCC: CLI execution |
| 302 | `test_status_json` | "status --json" prints valid JSON with items | exit 0, parseable JSON, items key present | UCC: CLI execution |
| 303 | `test_preflight_plain` | "preflight" prints gate results | "[GATE]" and "aria2_available" in stdout | UCC: CLI execution |
| 304 | `test_preflight_json` | "preflight --json" prints JSON with gates/status | parseable JSON, gates and status keys | UCC: CLI execution |
| 305 | `test_ucc_json` | "ucc --json" prints UCC structured result | exit 0, meta and result keys | UCC: CLI execution |
| 306 | `test_install_dry_run` | "install --dry-run" prints JSON plan | exit 0, ariaflow key in JSON | UCC: CLI execution |
| 307 | `test_uninstall_dry_run` | "uninstall --dry-run" prints JSON plan | exit 0, ariaflow key in JSON | UCC: CLI execution |
| 308 | `test_lifecycle` | "lifecycle" prints component statuses | exit 0, ariaflow and aria2 keys | UCC: CLI execution |

---

### `tests/test_web.py` — WebSmokeTests (7 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 309 | `test_local_web_server_smoke` | Full web server smoke test: all endpoints, add, pause/resume, run | all endpoints respond correctly, session/lifecycle/declaration/add/run work | UCC: API contract |
| 310 | `test_status_payload_does_not_synthesize_active_from_paused_queue_item` | Paused item with live_status=active shows live_status=paused in status | live_status == "paused", no active/actives keys, dedup collapses errors | UCC: observation consistency |
| 311 | `test_api_per_item_lifecycle` | Full per-item lifecycle: add→pause→resume→retry→remove via HTTP | all transitions correct, queue empty at end, 404/400 on invalid | ASM: all Job transitions |
| 312 | `test_api_aria2_options_rejects_unsafe` | Unsafe aria2 option rejected via real HTTP | code 400, error == "rejected_options" | UIC: policy enforcement |
| 313 | `test_api_openapi_and_docs` | OpenAPI YAML + Swagger UI + CORS via real HTTP | all served correctly | UCC: API contract |
| 314 | `test_api_tests_endpoint` | /api/tests returns test results (mocked subprocess) | ok, total == 1, passed == 1 | UCC: API contract |
| 315 | `test_run_start_honors_request_auto_preflight_override` | Request-level auto_preflight_on_run overrides declaration default | code 409, preflight_blocked, start_background_process not called | UIC: gate enforcement |

---

### `tests/test_homebrew_formula.py` — HomebrewFormulaScriptTests (3 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 316 | `test_version_from_tag_requires_stable_shape` | Alpha tag shape rejected with SystemExit | SystemExit raised | UCC: lifecycle |
| 317 | `test_version_from_tag_extracts_semver` | Stable tag extracts version string | "0.1.2" | UCC: lifecycle |
| 318 | `test_render_formula_uses_main_head_and_release_metadata` | Formula template uses correct URL, sha256, version, head | all fields present in rendered formula | UCC: lifecycle |

---

### `tests/test_release.py` — ReleaseScriptTests (5 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 319 | `test_parse_version_accepts_alpha_shape` | Alpha version parsed to 4-tuple | (0, 1, 1, 45) | UCC: lifecycle |
| 320 | `test_version_to_tag_requires_stable_semver` | Alpha version rejected for tag | SystemExit raised | UCC: lifecycle |
| 321 | `test_version_to_tag_uses_stable_tag_shape` | Stable version produces v-prefixed tag | "v0.1.2" | UCC: lifecycle |
| 322 | `test_build_plan_marks_manual_fallback_role` | Release plan has "explicit release dispatch helper" | plan[0] contains role, plan contains version | UCC: lifecycle |
| 323 | `test_build_plan_without_version_is_rebase_safe_push_helper` | Push plan has "rebase-safe main publish helper" | plan[0] contains role, version == none | UCC: lifecycle |

---

### `tests/test_aria2_rpc_wrappers.py` (40 tests)

All tests verify correct RPC method name, parameter passing, and return value extraction.

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 324 | `TestAria2AddUri::test_basic` | addUri with single URL | gid returned, correct method/params | BISS: aria2 boundary |
| 325 | `TestAria2AddUri::test_with_options` | addUri with options and custom port | gid returned, options in params | BISS: aria2 boundary |
| 326 | `TestAria2AddUri::test_with_position` | addUri with position argument | position == 0 in params | BISS: aria2 boundary |
| 327 | `TestAria2AddTorrent::test_basic` | addTorrent with base64 data | gid returned | BISS: aria2 boundary |
| 328 | `TestAria2AddTorrent::test_with_options` | addTorrent with uris and options | gid returned, all params passed | BISS: aria2 boundary |
| 329 | `TestAria2AddMetalink::test_returns_list` | addMetalink returns list of gids | list of 2 gids | BISS: aria2 boundary |
| 330 | `TestAria2Pause::test_pause` | aria2.pause called correctly | gid returned | BISS: aria2 boundary |
| 331 | `TestAria2ForcePause::test_force_pause` | aria2.forcePause called correctly | gid returned | BISS: aria2 boundary |
| 332 | `TestAria2PauseAll::test_pause_all` | aria2.pauseAll called correctly | "OK" returned | BISS: aria2 boundary |
| 333 | `TestAria2ForcePauseAll::test_force_pause_all` | aria2.forcePauseAll called correctly | "OK" returned | BISS: aria2 boundary |
| 334 | `TestAria2Unpause::test_unpause` | aria2.unpause called correctly | gid returned | BISS: aria2 boundary |
| 335 | `TestAria2UnpauseAll::test_unpause_all` | aria2.unpauseAll called correctly | "OK" returned | BISS: aria2 boundary |
| 336 | `TestAria2Remove::test_remove` | aria2.remove called correctly | gid returned | BISS: aria2 boundary |
| 337 | `TestAria2ForceRemove::test_force_remove` | aria2.forceRemove called correctly | gid returned | BISS: aria2 boundary |
| 338 | `TestAria2RemoveDownloadResult::test_remove_download_result` | aria2.removeDownloadResult called correctly | "OK" returned | BISS: aria2 boundary |
| 339 | `TestAria2TellStatus::test_tell_status` | aria2.tellStatus returns status dict | status == "active" | BISS: aria2 boundary |
| 340 | `TestAria2TellActive::test_tell_active` | aria2.tellActive returns list | len == 2 | BISS: aria2 boundary |
| 341 | `TestAria2TellActive::test_tell_active_error_returns_empty` | tellActive returns [] on error | result == [] | BISS: aria2 boundary (error) |
| 342 | `TestAria2TellWaiting::test_tell_waiting` | aria2.tellWaiting returns list | len == 1 | BISS: aria2 boundary |
| 343 | `TestAria2TellStopped::test_tell_stopped` | aria2.tellStopped returns list | len == 1 | BISS: aria2 boundary |
| 344 | `TestAria2TellStopped::test_tell_stopped_error_returns_empty` | tellStopped returns [] on error | result == [] | BISS: aria2 boundary (error) |
| 345 | `TestAria2GetFiles::test_get_files` | aria2.getFiles returns file list | len == 1 | BISS: aria2 boundary |
| 346 | `TestAria2GetUris::test_get_uris` | aria2.getUris returns URI list | uri == "http://a.com" | BISS: aria2 boundary |
| 347 | `TestAria2GetPeers::test_get_peers` | aria2.getPeers returns peer list | ip == "1.2.3.4" | BISS: aria2 boundary |
| 348 | `TestAria2GetServers::test_get_servers` | aria2.getServers returns server list | len == 1 | BISS: aria2 boundary |
| 349 | `TestAria2GetOption::test_get_option` | aria2.getOption returns options dict | dir == "/downloads" | BISS: aria2 boundary |
| 350 | `TestAria2ChangeOption::test_change_option` | aria2.changeOption called correctly | "OK" returned | BISS: aria2 boundary |
| 351 | `TestAria2GetGlobalOption::test_get_global_option` | aria2.getGlobalOption returns global options | max-concurrent-downloads == "5" | BISS: aria2 boundary |
| 352 | `TestAria2ChangeGlobalOption::test_change_global_option` | aria2.changeGlobalOption called correctly | "OK" returned | BISS: aria2 boundary |
| 353 | `TestAria2GetGlobalStat::test_get_global_stat` | aria2.getGlobalStat returns stats | numActive == "2" | BISS: aria2 boundary |
| 354 | `TestAria2ChangePosition::test_change_position` | aria2.changePosition called correctly | position == 0 | BISS: aria2 boundary |
| 355 | `TestAria2ChangeUri::test_change_uri` | aria2.changeUri swaps URIs | result == [1, 1] | BISS: aria2 boundary |
| 356 | `TestAria2ChangeUri::test_change_uri_with_position` | aria2.changeUri with position arg | position == 0 in params | BISS: aria2 boundary |
| 357 | `TestAria2PurgeDownloadResult::test_purge` | aria2.purgeDownloadResult called correctly | "OK" returned | BISS: aria2 boundary |
| 358 | `TestAria2GetVersion::test_get_version` | aria2.getVersion returns version info | version == "1.37.0" | BISS: aria2 boundary |
| 359 | `TestAria2GetSessionInfo::test_get_session_info` | aria2.getSessionInfo returns session info | sessionId == "abc123" | BISS: aria2 boundary |
| 360 | `TestAria2SaveSession::test_save_session` | aria2.saveSession called correctly | "OK" returned | BISS: aria2 boundary |
| 361 | `TestAria2Shutdown::test_shutdown` | aria2.shutdown called correctly | "OK" returned | BISS: aria2 boundary |
| 362 | `TestAria2ForceShutdown::test_force_shutdown` | aria2.forceShutdown called correctly | "OK" returned | BISS: aria2 boundary |
| 363 | `TestAria2Multicall::test_multicall` | system.multicall batches calls | len == 2 | BISS: aria2 boundary |
| 364 | `TestAria2ListMethods::test_list_methods` | system.listMethods returns method list | "aria2.addUri" in methods | BISS: aria2 boundary |
| 365 | `TestAria2ListNotifications::test_list_notifications` | system.listNotifications returns notification list | "aria2.onDownloadStart" in notifs | BISS: aria2 boundary |
| 366 | `TestPortOverride::test_pause_custom_port` | Custom port forwarded to aria_rpc for pause | port == 7000 | BISS: aria2 boundary |
| 367 | `TestPortOverride::test_shutdown_custom_port` | Custom port forwarded to aria_rpc for shutdown | port == 9999 | BISS: aria2 boundary |

---

### `tests/scheduler/test_queue_scheduler.py` — QueueSchedulerTests (7 tests)

| # | Test | Intent | Oracle | Trace Target |
|---|---|---|---|---|
| 368 | `test_process_queue_submits_all_queued_items_to_aria2` | All queued items submitted to aria2 | add_download called twice | ASM: Run+Job axis |
| 369 | `test_process_queue_respects_runner_paused_state_and_starts_no_new_downloads` | Paused runner starts no new downloads | add_download not called, paused stays True | ASM: Run axis |
| 370 | `test_process_queue_honors_active_slot_limit_before_starting_new_work` | Slot limit respected (1 active, 1 queued → only queued submitted) | add_download called once | ASM: Coherence CR-6 |
| 371 | `test_cleanup_queue_state_collapses_duplicate_nonterminal_rows` | Duplicate paused rows collapsed to one (keeps most advanced) | len(items) == 1, completedLength == "20" | UCC: queue integrity |
| 372 | `test_cleanup_queue_state_collapses_duplicate_error_rows` | Duplicate error rows collapsed to one | len(items) == 1, recovery fields preserved | UCC: queue integrity |
| 373 | `test_cleanup_queue_state_normalizes_stale_live_status_for_paused_item` | Paused item with live_status=active normalized to paused | live_status == "paused", normalized == 1 | ASM: Job state normalization |
| 374 | `test_process_queue_runs_startup_cleanup_before_reconcile` | Startup cleanup runs before reconcile, deduplicates | len(items) == 1, completedLength == "20" | UCC: execution order |

---

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
| UIC: policy enforcement | 16 |
| UCC: execution results | 30 |
| UCC: observation consistency | 25 |
| UCC: error semantics | 30 |
| UCC: API contract shape | 52 |
| UCC: audit trail | 16 |
| UCC: lifecycle | 16 |
| UCC: concurrency / safety | 8 |
| UCC: input boundary (security) | 14 |
| UCC: CLI contract | 25 |
| UCC: revision | 6 |
| BISS: aria2 boundary | 42 |
| **Total** | **374** |
