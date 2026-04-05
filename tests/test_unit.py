"""Unit tests covering core functionality.

Covers:
- Storage paths (config_dir, queue_path, state_path, log_path, etc.)
- JSON read/write with corruption recovery
- State session lifecycle (ensure, touch, close, history, stats)
- Action log and archive operations
- Queue auto-cleanup and transfer polling
- Download mode detection and queue item lookup
- Queue summarization
- Contracts (declaration path, ensure_declaration)
- Install helpers (version, ucc_envelope, ucc_record)
- Bonjour service advertisement
- aria2 RPC wrappers (bandwidth limit, managed set functions)
- Transfer pause and background process stop
- Bandwidth config, status, and manual probe
- allowed_actions per item status
- Scheduler auto-retry with policy
- aria2 max-tries passthrough
- Option tiers discovery
- 3-tier option safety
"""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import IsolatedTestCase

_MODULE = "aria_queue.core"


# ── storage.py ──────────────────────────────────────────────────────


class TestStoragePaths(IsolatedTestCase):
    def test_config_dir_returns_path(self) -> None:
        from aria_queue.core import config_dir
        result = config_dir()
        self.assertIsInstance(result, Path)
        self.assertEqual(str(result), self._tmp.name)

    def test_queue_path(self) -> None:
        from aria_queue.core import config_dir, queue_path
        self.assertEqual(queue_path(), config_dir() / "queue.json")

    def test_state_path(self) -> None:
        from aria_queue.core import config_dir, state_path
        self.assertEqual(state_path(), config_dir() / "state.json")

    def test_log_path(self) -> None:
        from aria_queue.core import config_dir, log_path
        self.assertEqual(log_path(), config_dir() / "aria2.log")

    def test_action_log_path(self) -> None:
        from aria_queue.core import config_dir, action_log_path
        self.assertEqual(action_log_path(), config_dir() / "actions.jsonl")

    def test_archive_path(self) -> None:
        from aria_queue.core import config_dir, archive_path
        self.assertEqual(archive_path(), config_dir() / "archive.json")

    def test_sessions_log_path(self) -> None:
        from aria_queue.core import config_dir, sessions_log_path
        self.assertEqual(sessions_log_path(), config_dir() / "sessions.jsonl")

    def test_storage_lock_path(self) -> None:
        from aria_queue.core import config_dir, storage_lock_path
        self.assertEqual(storage_lock_path(), config_dir() / ".storage.lock")


class TestEnsureStorage(IsolatedTestCase):
    def test_creates_directory(self) -> None:
        from aria_queue.core import ensure_storage, config_dir
        subdir = Path(self._tmp.name) / "sub" / "dir"
        os.environ["ARIA_QUEUE_DIR"] = str(subdir)
        ensure_storage()
        self.assertTrue(subdir.is_dir())


class TestReadJson(IsolatedTestCase):
    def test_normal_read(self) -> None:
        from aria_queue.core import read_json
        p = Path(self._tmp.name) / "data.json"
        p.write_text(json.dumps({"a": 1}), encoding="utf-8")
        self.assertEqual(read_json(p, {}), {"a": 1})

    def test_missing_file_returns_default(self) -> None:
        from aria_queue.core import read_json
        p = Path(self._tmp.name) / "nope.json"
        self.assertEqual(read_json(p, []), [])

    def test_corrupted_file_creates_backup(self) -> None:
        from aria_queue.core import read_json
        p = Path(self._tmp.name) / "bad.json"
        p.write_text("{{{not json", encoding="utf-8")
        result = read_json(p, "default")
        self.assertEqual(result, "default")
        bak = p.with_suffix(".json.corrupt.bak")
        self.assertTrue(bak.exists())


class TestWriteJson(IsolatedTestCase):
    def test_write_then_read(self) -> None:
        from aria_queue.core import read_json, write_json
        p = Path(self._tmp.name) / "rw.json"
        write_json(p, {"x": 42})
        self.assertEqual(read_json(p, None), {"x": 42})


# ── state.py ────────────────────────────────────────────────────────


class TestEnsureStateSession(IsolatedTestCase):
    def test_creates_session_id(self) -> None:
        from aria_queue.core import ensure_state_session
        state = ensure_state_session()
        self.assertIsNotNone(state.get("session_id"))
        self.assertIsNotNone(state.get("session_started_at"))


class TestTouchStateSession(IsolatedTestCase):
    def test_updates_last_seen(self) -> None:
        from aria_queue.core import ensure_state_session, touch_state_session
        ensure_state_session()
        state = touch_state_session()
        self.assertIsNotNone(state.get("session_last_seen_at"))


class TestCloseStateSession(IsolatedTestCase):
    def test_sets_closed_fields(self) -> None:
        from aria_queue.core import ensure_state_session, close_state_session
        ensure_state_session()
        state = close_state_session("test_reason")
        self.assertIsNotNone(state.get("session_closed_at"))
        self.assertEqual(state.get("session_closed_reason"), "test_reason")


class TestLoadSessionHistory(IsolatedTestCase):
    def test_returns_list(self) -> None:
        from aria_queue.core import load_session_history
        result = load_session_history()
        self.assertIsInstance(result, list)


class TestSessionStats(IsolatedTestCase):
    def test_returns_dict_with_keys(self) -> None:
        from aria_queue.core import ensure_state_session, session_stats
        ensure_state_session()
        result = session_stats()
        self.assertIsInstance(result, dict)
        for key in ("session_id", "items_total", "items_done", "items_error",
                     "items_queued", "items_downloading", "items_paused",
                     "bytes_completed"):
            self.assertIn(key, result)


class TestAppendActionLog(IsolatedTestCase):
    def test_appends_entry(self) -> None:
        from aria_queue.core import append_action_log, action_log_path
        append_action_log({"action": "test", "target": "unit"})
        lines = action_log_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)
        entry = json.loads(lines[-1])
        self.assertEqual(entry["action"], "test")


class TestLoadArchive(IsolatedTestCase):
    def test_returns_list(self) -> None:
        from aria_queue.core import load_archive
        self.assertIsInstance(load_archive(), list)


class TestSaveArchive(IsolatedTestCase):
    def test_roundtrip(self) -> None:
        from aria_queue.core import save_archive, load_archive
        items = [{"id": "a", "status": "complete"}]
        save_archive(items)
        self.assertEqual(load_archive(), items)


class TestArchiveItem(IsolatedTestCase):
    def test_adds_to_archive(self) -> None:
        from aria_queue.core import archive_item, load_archive
        archive_item({"id": "x", "status": "complete"})
        archived = load_archive()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["id"], "x")
        self.assertIn("archived_at", archived[0])


class TestAutoCleanupQueue(IsolatedTestCase):
    def test_removes_old_done(self) -> None:
        from aria_queue.core import (
            auto_cleanup_queue, save_queue, load_queue, load_archive,
            ensure_storage,
        )
        ensure_storage()
        old_time = "2020-01-01T00:00:00+00:00"
        items = [
            {"id": "1", "status": "complete", "completed_at": old_time},
            {"id": "2", "status": "queued"},
        ]
        save_queue(items)
        result = auto_cleanup_queue(max_done_age_days=1)
        self.assertEqual(result["archived"], 1)
        remaining = load_queue()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["id"], "2")


class TestLogTransferPoll(IsolatedTestCase):
    def test_appends_to_action_log(self) -> None:
        from aria_queue.core import log_transfer_poll, action_log_path
        log_transfer_poll(
            gid="abc",
            item={"id": "1", "url": "http://x"},
            info={"status": "active", "downloadSpeed": "100"},
        )
        self.assertTrue(action_log_path().exists())
        lines = action_log_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)


# ── queue_ops.py ────────────────────────────────────────────────────


class TestDetectDownloadMode(unittest.TestCase):
    def test_http(self) -> None:
        from aria_queue.core import detect_download_mode
        self.assertEqual(detect_download_mode("http://example.com/file.zip"), "http")

    def test_magnet(self) -> None:
        from aria_queue.core import detect_download_mode
        self.assertEqual(detect_download_mode("magnet:?xt=urn:btih:abc"), "magnet")

    def test_torrent(self) -> None:
        from aria_queue.core import detect_download_mode
        self.assertEqual(detect_download_mode("http://x/file.torrent"), "torrent")

    def test_metalink(self) -> None:
        from aria_queue.core import detect_download_mode
        self.assertEqual(detect_download_mode("http://x/file.metalink"), "metalink")
        self.assertEqual(detect_download_mode("http://x/file.meta4"), "metalink")

    def test_mirror(self) -> None:
        from aria_queue.core import detect_download_mode
        self.assertEqual(
            detect_download_mode("http://a/f", mirrors=["http://a/f", "http://b/f"]),
            "mirror",
        )


class TestFindQueueItemByGid(IsolatedTestCase):
    def test_finds_item(self) -> None:
        from aria_queue.core import find_queue_item_by_gid, save_queue
        save_queue([{"id": "1", "gid": "g1", "status": "active"}])
        result = find_queue_item_by_gid("g1")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "1")

    def test_returns_none_for_missing(self) -> None:
        from aria_queue.core import find_queue_item_by_gid, save_queue
        save_queue([])
        self.assertIsNone(find_queue_item_by_gid("nope"))


class TestSummarizeQueue(unittest.TestCase):
    def test_counts_by_status(self) -> None:
        from aria_queue.core import summarize_queue
        items = [
            {"status": "queued"},
            {"status": "queued"},
            {"status": "active"},
            {"status": "complete"},
        ]
        result = summarize_queue(items)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["queued"], 2)
        self.assertEqual(result["active"], 1)
        self.assertEqual(result["complete"], 1)


# ── contracts.py ────────────────────────────────────────────────────


class TestDeclarationPath(IsolatedTestCase):
    def test_returns_path(self) -> None:
        from aria_queue.contracts import declaration_path
        result = declaration_path()
        self.assertIsInstance(result, Path)
        self.assertTrue(str(result).endswith("declaration.json"))


class TestEnsureDeclaration(IsolatedTestCase):
    def test_creates_default(self) -> None:
        from aria_queue.contracts import ensure_declaration, declaration_path
        result = ensure_declaration()
        self.assertIsInstance(result, dict)
        self.assertIn("meta", result)
        self.assertTrue(declaration_path().exists())


# ── install.py ──────────────────────────────────────────────────────


class TestCurrentAriaflowVersion(unittest.TestCase):
    def test_returns_string(self) -> None:
        from aria_queue.install import current_ariaflow_version
        v = current_ariaflow_version()
        self.assertIsInstance(v, str)
        self.assertTrue(len(v) > 0)


class TestUccEnvelope(unittest.TestCase):
    def test_returns_dict_with_keys(self) -> None:
        from aria_queue.install import ucc_envelope
        result = ucc_envelope(
            target="queue", observed=True, outcome="ok",
        )
        self.assertIn("meta", result)
        self.assertIn("result", result)
        self.assertEqual(result["meta"]["target"], "queue")
        self.assertEqual(result["result"]["outcome"], "ok")


class TestUccRecord(unittest.TestCase):
    def test_returns_dict(self) -> None:
        from aria_queue.install import ucc_record
        result = ucc_record(target="t", observed=False, outcome="fail")
        self.assertIn("meta", result)
        self.assertEqual(result["result"]["observation"], "failed")


# ── bonjour.py ──────────────────────────────────────────────────────


class TestBonjourAvailable(unittest.TestCase):
    def test_returns_bool(self) -> None:
        from aria_queue.bonjour import bonjour_available
        self.assertIsInstance(bonjour_available(), bool)


class TestAdvertiseHttpService(unittest.TestCase):
    @patch("aria_queue.bonjour._detect_backend", return_value=None)
    def test_context_manager_noop(self, _mock: MagicMock) -> None:
        from aria_queue.bonjour import advertise_http_service
        with advertise_http_service(port=8080):
            pass  # should not crash


class TestBonjourCommandConstruction(unittest.TestCase):
    @patch("aria_queue.bonjour._device_name", return_value="myhost")
    @patch("aria_queue.bonjour.getpass.getuser", return_value="testuser")
    def test_dns_sd_cmd_structure(self, _user: MagicMock, _dev: MagicMock) -> None:
        from aria_queue.bonjour import build_dns_sd_cmd
        cmd = build_dns_sd_cmd(port=8000, path="/api")
        self.assertEqual(cmd[2], "testuser's myhost AriaFlow")
        self.assertEqual(cmd[3], "_ariaflow._tcp")
        self.assertEqual(cmd[4], "local")
        self.assertEqual(cmd[5], "8000")
        self.assertIn("path=/api", cmd)
        self.assertIn("tls=0", cmd)
        # Removed TXT records should not be present
        for arg in cmd:
            self.assertNotIn("role=", arg) if "=" in arg and arg.startswith("role=") else None
            self.assertNotIn("proto=", arg) if "=" in arg and arg.startswith("proto=") else None
            self.assertNotIn("product=", arg) if "=" in arg and arg.startswith("product=") else None

    @patch("aria_queue.bonjour._device_name", return_value="myhost")
    @patch("aria_queue.bonjour.getpass.getuser", return_value="testuser")
    def test_avahi_cmd_structure(self, _user: MagicMock, _dev: MagicMock) -> None:
        from aria_queue.bonjour import build_avahi_cmd
        cmd = build_avahi_cmd(port=8000, path="/api")
        self.assertEqual(cmd[1], "testuser's myhost AriaFlow")
        self.assertEqual(cmd[2], "_ariaflow._tcp")
        self.assertEqual(cmd[3], "8000")
        self.assertIn("path=/api", cmd)
        self.assertIn("tls=0", cmd)

    @patch("aria_queue.bonjour._device_name", return_value="myhost")
    @patch("aria_queue.bonjour.getpass.getuser", return_value="testuser")
    def test_dns_sd_and_avahi_same_service_type(self, _user: MagicMock, _dev: MagicMock) -> None:
        from aria_queue.bonjour import build_dns_sd_cmd, build_avahi_cmd
        kwargs = dict(port=8000, path="/api")
        dns_cmd = build_dns_sd_cmd(**kwargs)
        avahi_cmd = build_avahi_cmd(**kwargs)
        self.assertEqual(dns_cmd[3], "_ariaflow._tcp")
        self.assertEqual(avahi_cmd[2], "_ariaflow._tcp")

    @patch("aria_queue.bonjour._device_name", return_value="myhost")
    @patch("aria_queue.bonjour.getpass.getuser", return_value="testuser")
    def test_dns_sd_and_avahi_same_txt_records(self, _user: MagicMock, _dev: MagicMock) -> None:
        from aria_queue.bonjour import build_dns_sd_cmd, build_avahi_cmd
        kwargs = dict(port=8000, path="/api")
        dns_txt = set(s for s in build_dns_sd_cmd(**kwargs) if "=" in s)
        avahi_txt = set(s for s in build_avahi_cmd(**kwargs) if "=" in s)
        self.assertEqual(dns_txt, avahi_txt)

    def test_instance_name_truncates_at_63_bytes(self) -> None:
        from aria_queue.bonjour import _instance_name
        with patch("aria_queue.bonjour.getpass.getuser", return_value="a" * 80), \
             patch("aria_queue.bonjour._device_name", return_value="host"):
            name = _instance_name()
            self.assertLessEqual(len(name.encode("utf-8")), 63)

    def test_txt_keys_max_9_chars(self) -> None:
        """All TXT record keys must be ≤9 characters (Apple best practice)."""
        from aria_queue.bonjour import build_dns_sd_cmd
        with patch("aria_queue.bonjour.getpass.getuser", return_value="test"), \
             patch("aria_queue.bonjour._device_name", return_value="host"):
            cmd = build_dns_sd_cmd(port=8000, path="/api")
        for arg in cmd:
            if "=" in arg:
                key = arg.split("=", 1)[0]
                self.assertLessEqual(len(key), 9, f"TXT key '{key}' exceeds 9 chars")

    def test_service_type_max_15_chars(self) -> None:
        """Service type must be ≤15 characters (excluding underscore prefix)."""
        from aria_queue.bonjour import build_dns_sd_cmd
        with patch("aria_queue.bonjour.getpass.getuser", return_value="test"), \
             patch("aria_queue.bonjour._device_name", return_value="host"):
            cmd = build_dns_sd_cmd(port=8000, path="/api")
        svc_type = cmd[3]  # _ariaflow._tcp
        name_part = svc_type.split(".")[0].lstrip("_")  # ariaflow
        self.assertLessEqual(len(name_part), 15, f"Service type '{name_part}' exceeds 15 chars")


# ── aria2_rpc.py ────────────────────────────────────────────────────


class TestAria2SetDownloadBandwidth(unittest.TestCase):
    @patch("aria_queue.aria2_rpc.aria2_change_option")
    def test_calls_change_option(self, mock_co: MagicMock) -> None:
        from aria_queue.aria2_rpc import aria2_set_max_download_limit
        aria2_set_max_download_limit("gid1", 1000, port=6800)
        mock_co.assert_called_once()
        args, kwargs = mock_co.call_args
        self.assertEqual(args[0], "gid1")


# ── transfers.py ────────────────────────────────────────────────────


class TestPauseActiveTransfer(IsolatedTestCase):
    @patch("aria_queue.core.aria2_tell_active", return_value=[])
    def test_no_active_returns_not_paused(self, _mock: MagicMock) -> None:
        from aria_queue.core import pause_active_transfer, ensure_storage
        ensure_storage()
        result = pause_active_transfer()
        self.assertFalse(result["paused"])
        self.assertEqual(result["reason"], "no_active_transfer")


# ── scheduler.py ────────────────────────────────────────────────────


class TestStopBackgroundProcess(IsolatedTestCase):
    def test_not_running_returns_stopped_false(self) -> None:
        from aria_queue.core import stop_background_process, ensure_storage
        ensure_storage()
        result = stop_background_process()
        self.assertFalse(result["stopped"])
        self.assertEqual(result["reason"], "not_running")


# ── bandwidth.py ────────────────────────────────────────────────────


class TestBandwidthConfig(IsolatedTestCase):
    def test_returns_dict_with_free_percent(self) -> None:
        from aria_queue.core import bandwidth_config, ensure_storage

        ensure_storage()
        result = bandwidth_config()
        self.assertIsInstance(result, dict)
        self.assertIn("down_free_percent", result)
        self.assertIn("probe_interval_seconds", result)


class TestBandwidthStatus(IsolatedTestCase):
    @patch("aria_queue.core.aria2_current_bandwidth", return_value={"limit": "0"})
    def test_returns_dict_with_config_and_bandwidth(self, _mock: MagicMock) -> None:
        from aria_queue.core import bandwidth_status, ensure_storage

        ensure_storage()
        result = bandwidth_status()
        self.assertIsInstance(result, dict)
        self.assertIn("config", result)
        self.assertIn("current_limit", result)


class TestManualProbe(IsolatedTestCase):
    @patch("aria_queue.core.probe_bandwidth", return_value={
        "source": "default",
        "reason": "probe_unavailable",
        "cap_mbps": 2,
        "cap_bytes_per_sec": 250000,
    })
    @patch("aria_queue.core.aria2_set_max_overall_download_limit")
    def test_returns_probe_result(self, _set: MagicMock, _probe: MagicMock) -> None:
        from aria_queue.core import manual_probe, ensure_storage

        ensure_storage()
        result = manual_probe()
        self.assertIsInstance(result, dict)
        self.assertIn("probe", result)


# ── allowed_actions ─────────────────────────────────────────────────


class TestAllowedActions(unittest.TestCase):
    def test_queued_allows_pause_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("queued"), ["pause", "remove"])

    def test_active_allows_pause_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("active"), ["pause", "remove"])

    def test_waiting_allows_pause_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("waiting"), ["pause", "remove"])

    def test_paused_allows_resume_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("paused"), ["resume", "remove"])

    def test_complete_allows_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("complete"), ["remove"])

    def test_error_allows_retry_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("error"), ["retry", "remove"])

    def test_stopped_allows_retry_remove(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("stopped"), ["retry", "remove"])

    def test_cancelled_allows_nothing(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("cancelled"), [])

    def test_unknown_status_allows_nothing(self) -> None:
        from aria_queue.queue_ops import allowed_actions

        self.assertEqual(allowed_actions("nonexistent"), [])


# ── auto-retry ──────────────────────────────────────────────────────


class TestAutoRetry(IsolatedTestCase):
    def _setup_error_item(self) -> None:
        from aria_queue.core import add_queue_item, save_queue, load_queue, ensure_storage

        ensure_storage()
        add_queue_item("https://example.com/retry-test.bin")
        items = load_queue()
        items[0]["status"] = "error"
        items[0]["error_code"] = "5"
        items[0]["error_message"] = "download failed"
        items[0]["error_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        items[0]["gid"] = "gid-err"
        save_queue(items)

    def test_auto_retry_requeues_error_item(self) -> None:
        self._setup_error_item()
        from aria_queue.core import load_queue, save_queue, load_state, save_state, ensure_storage

        ensure_storage()
        state = load_state()
        state["running"] = True
        save_state(state)

        with (
            patch(f"{_MODULE}.aria2_ensure_daemon"),
            patch(f"{_MODULE}.deduplicate_active_transfers"),
            patch(f"{_MODULE}.reconcile_live_queue"),
            patch(f"{_MODULE}.probe_bandwidth", return_value={
                "source": "default", "reason": "probe_unavailable",
                "cap_mbps": 2, "cap_bytes_per_sec": 250000,
            }),
            patch(f"{_MODULE}.aria2_current_bandwidth", return_value={}),
            patch(f"{_MODULE}.aria2_set_max_overall_download_limit"),
            patch(f"{_MODULE}.aria2_tell_active", return_value=[]),
            patch(f"{_MODULE}.aria2_multicall", return_value=[]),
            patch(f"{_MODULE}.aria2_add_download", return_value="gid-new"),
            patch(f"{_MODULE}.time.sleep", side_effect=RuntimeError("stop")),
        ):
            from aria_queue.core import process_queue

            with self.assertRaisesRegex(RuntimeError, "stop"):
                process_queue()

        items = load_queue()
        self.assertEqual(items[0]["status"], "active")
        self.assertEqual(items[0]["retry_count"], 1)

    def test_auto_retry_skips_rpc_unreachable(self) -> None:
        self._setup_error_item()
        from aria_queue.core import load_queue, save_queue, load_state, save_state, ensure_storage, add_queue_item

        ensure_storage()
        add_queue_item("https://example.com/keep-alive.bin")  # keep loop alive
        items = load_queue()
        for item in items:
            if item.get("error_code"):
                item["error_code"] = "rpc_unreachable"
        save_queue(items)
        state = load_state()
        state["running"] = True
        save_state(state)

        with (
            patch(f"{_MODULE}.aria2_ensure_daemon"),
            patch(f"{_MODULE}.deduplicate_active_transfers"),
            patch(f"{_MODULE}.reconcile_live_queue"),
            patch(f"{_MODULE}.probe_bandwidth", return_value={
                "source": "default", "reason": "probe_unavailable",
                "cap_mbps": 2, "cap_bytes_per_sec": 250000,
            }),
            patch(f"{_MODULE}.aria2_current_bandwidth", return_value={}),
            patch(f"{_MODULE}.aria2_set_max_overall_download_limit"),
            patch(f"{_MODULE}.aria2_tell_active", return_value=[]),
            patch(f"{_MODULE}.aria2_multicall", return_value=[]),
            patch(f"{_MODULE}.time.sleep", side_effect=RuntimeError("stop")),
        ):
            from aria_queue.core import process_queue

            with self.assertRaisesRegex(RuntimeError, "stop"):
                process_queue()

        items = load_queue()
        self.assertEqual(items[0]["status"], "error")  # NOT retried

    def test_auto_retry_respects_max_retries(self) -> None:
        self._setup_error_item()
        from aria_queue.core import load_queue, save_queue, ensure_storage, add_queue_item

        ensure_storage()
        add_queue_item("https://example.com/keep-alive.bin")  # keep loop alive
        items = load_queue()
        for item in items:
            if item.get("error_code"):
                item["retry_count"] = 3  # already at max
        save_queue(items)

        from aria_queue.core import load_state, save_state

        state = load_state()
        state["running"] = True
        save_state(state)

        with (
            patch(f"{_MODULE}.aria2_ensure_daemon"),
            patch(f"{_MODULE}.deduplicate_active_transfers"),
            patch(f"{_MODULE}.reconcile_live_queue"),
            patch(f"{_MODULE}.probe_bandwidth", return_value={
                "source": "default", "reason": "probe_unavailable",
                "cap_mbps": 2, "cap_bytes_per_sec": 250000,
            }),
            patch(f"{_MODULE}.aria2_current_bandwidth", return_value={}),
            patch(f"{_MODULE}.aria2_set_max_overall_download_limit"),
            patch(f"{_MODULE}.aria2_tell_active", return_value=[]),
            patch(f"{_MODULE}.aria2_multicall", return_value=[]),
            patch(f"{_MODULE}.time.sleep", side_effect=RuntimeError("stop")),
        ):
            from aria_queue.core import process_queue

            with self.assertRaisesRegex(RuntimeError, "stop"):
                process_queue()

        items = load_queue()
        self.assertEqual(items[0]["status"], "error")  # NOT retried


# ── aria2 max-tries passthrough ─────────────────────────────────────


class TestAria2MaxTriesPassthrough(IsolatedTestCase):
    def test_add_download_includes_max_tries(self) -> None:
        from aria_queue.core import ensure_storage

        ensure_storage()
        mock_rpc = MagicMock(return_value={"result": "gid-1"})
        with patch(f"{_MODULE}.aria_rpc", mock_rpc):
            from aria_queue.aria2_rpc import aria2_add_download

            aria2_add_download(
                {"url": "http://example.com/f", "mode": "http"},
                cap_bytes_per_sec=0,
            )
        call_args = mock_rpc.call_args
        options = call_args[0][1][1]  # params[1] = options dict
        self.assertIn("max-tries", options)
        self.assertIn("retry-wait", options)
        self.assertEqual(options["max-tries"], "5")
        self.assertEqual(options["retry-wait"], "10")


# ── option_tiers endpoint ───────────────────────────────────────────


class TestOptionTiers(IsolatedTestCase):
    def test_returns_three_tiers(self) -> None:
        from aria_queue.aria2_rpc import _MANAGED_ARIA2_OPTIONS, _SAFE_ARIA2_OPTIONS
        from aria_queue.queue_ops import allowed_actions  # just to verify import works

        self.assertIn("max-overall-download-limit", _MANAGED_ARIA2_OPTIONS)
        self.assertIn("max-overall-upload-limit", _MANAGED_ARIA2_OPTIONS)
        self.assertIn("seed-ratio", _MANAGED_ARIA2_OPTIONS)
        self.assertIn("max-concurrent-downloads", _SAFE_ARIA2_OPTIONS)
        self.assertNotIn("max-overall-download-limit", _SAFE_ARIA2_OPTIONS)


# ── managed aria2_set_* functions ───────────────────────────────────


class TestManagedSetFunctions(unittest.TestCase):
    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_max_overall_upload_limit(self) -> None:
        from aria_queue.core import aria2_set_max_overall_upload_limit

        aria2_set_max_overall_upload_limit(500000)

    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_max_upload_limit(self) -> None:
        from aria_queue.core import aria2_set_max_upload_limit

        aria2_set_max_upload_limit("gid-1", 100000)

    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_seed_ratio(self) -> None:
        from aria_queue.core import aria2_set_seed_ratio

        aria2_set_seed_ratio(2.0)

    @patch(f"{_MODULE}.aria_rpc", MagicMock(return_value={"result": "OK"}))
    def test_set_seed_time(self) -> None:
        from aria_queue.core import aria2_set_seed_time

        aria2_set_seed_time(60)


# ── 3-tier safety ───────────────────────────────────────────────────


class TestThreeTierSafety(IsolatedTestCase):
    def test_managed_option_rejected(self) -> None:
        from aria_queue.core import aria2_change_options, ensure_storage

        ensure_storage()
        result = aria2_change_options({"max-overall-download-limit": "100K"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "managed_options")

    def test_safe_option_accepted(self) -> None:
        from aria_queue.core import aria2_change_options, ensure_storage

        ensure_storage()
        with (
            patch(f"{_MODULE}.aria_rpc"),
            patch(f"{_MODULE}.aria2_current_global_options", return_value={}),
        ):
            result = aria2_change_options({"max-concurrent-downloads": "5"})
        self.assertTrue(result["ok"])

    def test_unsafe_option_rejected_by_default(self) -> None:
        from aria_queue.core import aria2_change_options, ensure_storage

        ensure_storage()
        result = aria2_change_options({"dir": "/tmp"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "rejected_options")


# ── scheduler.py — seed expiration ─────────────────────────────────


class TestSeedExpiration(IsolatedTestCase):
    def _make_seeding_item(self, started_at: str) -> dict[str, Any]:
        return {
            "id": "item-seed-1",
            "url": "https://example.com/file.bin",
            "status": "done",
            "distribute_status": "seeding",
            "distribute_started_at": started_at,
            "distribute_seed_gid": "seed-gid-1",
            "distribute_infohash": "abc123",
            "distribute_torrent_path": "/tmp/test.torrent",
            "gid": "",
            "priority": 0,
        }

    @patch("aria_queue.core.aria2_add_download", return_value="gid-1")
    @patch("aria_queue.core.aria2_remove")
    @patch("aria_queue.core.aria2_tell_active", return_value=[])
    @patch("aria_queue.core.aria2_tell_waiting", return_value=[])
    @patch("aria_queue.core.aria2_ensure_daemon")
    @patch("aria_queue.core.aria2_change_global_option")
    @patch("aria_queue.core.deduplicate_active_transfers")
    @patch("aria_queue.core.reconcile_live_queue")
    @patch("aria_queue.core._apply_bandwidth_probe", return_value=({}, 100.0, 12500000))
    def test_seed_expires_by_time(
        self, _probe: MagicMock, _reconcile: MagicMock, _dedup: MagicMock,
        _global: MagicMock, _daemon: MagicMock, _waiting: MagicMock,
        _active: MagicMock, mock_remove: MagicMock, _add: MagicMock,
    ) -> None:
        import datetime
        from aria_queue.core import (
            ensure_storage, save_queue, save_state, load_queue,
            ensure_state_session, process_queue,
        )
        ensure_storage()
        state = ensure_state_session()
        state["running"] = True
        save_state(state)
        # Seed started 100 hours ago
        old_time = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=100)
        ).strftime("%Y-%m-%dT%H:%M:%S+0000")
        item = self._make_seeding_item(old_time)
        save_queue([item])

        # Set max_seed_hours=72 via declaration
        from aria_queue.contracts import ensure_declaration, declaration_path
        import json
        decl = ensure_declaration()
        for pref in decl.get("uic", {}).get("preferences", []):
            if pref["name"] == "distribute_max_seed_hours":
                pref["value"] = 72
        declaration_path().write_text(json.dumps(decl), encoding="utf-8")

        process_queue(port=6800)
        items = load_queue()
        expired = [i for i in items if i.get("distribute_status") == "expired"]
        self.assertEqual(len(expired), 1)
        mock_remove.assert_called_once()

    @patch("aria_queue.core.aria2_add_download", return_value="gid-1")
    @patch("aria_queue.core.aria2_remove")
    @patch("aria_queue.core.aria2_tell_active", return_value=[])
    @patch("aria_queue.core.aria2_tell_waiting", return_value=[])
    @patch("aria_queue.core.aria2_ensure_daemon")
    @patch("aria_queue.core.aria2_change_global_option")
    @patch("aria_queue.core.deduplicate_active_transfers")
    @patch("aria_queue.core.reconcile_live_queue")
    @patch("aria_queue.core._apply_bandwidth_probe", return_value=({}, 100.0, 12500000))
    def test_seed_not_expired_when_recent(
        self, _probe: MagicMock, _reconcile: MagicMock, _dedup: MagicMock,
        _global: MagicMock, _daemon: MagicMock, _waiting: MagicMock,
        _active: MagicMock, mock_remove: MagicMock, _add: MagicMock,
    ) -> None:
        import datetime
        from aria_queue.core import (
            ensure_storage, save_queue, save_state, load_queue,
            ensure_state_session, process_queue,
        )
        ensure_storage()
        state = ensure_state_session()
        state["running"] = True
        save_state(state)
        # Seed started 1 hour ago
        recent_time = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%dT%H:%M:%S+0000")
        item = self._make_seeding_item(recent_time)
        save_queue([item])

        from aria_queue.contracts import ensure_declaration, declaration_path
        import json
        decl = ensure_declaration()
        for pref in decl.get("uic", {}).get("preferences", []):
            if pref["name"] == "distribute_max_seed_hours":
                pref["value"] = 72
        declaration_path().write_text(json.dumps(decl), encoding="utf-8")

        process_queue(port=6800)
        items = load_queue()
        still_seeding = [i for i in items if i.get("distribute_status") == "seeding"]
        self.assertEqual(len(still_seeding), 1)
        mock_remove.assert_not_called()


# ── bonjour.py — record_action observability ───────────────────────


class TestBonjourRecordAction(IsolatedTestCase):
    @patch("aria_queue.bonjour._detect_backend", return_value=None)
    def test_http_service_skipped_logs_action(self, _mock: MagicMock) -> None:
        from aria_queue.bonjour import advertise_http_service
        from aria_queue.core import ensure_storage, load_action_log
        ensure_storage()
        with advertise_http_service(port=8080):
            pass
        entries = load_action_log()
        register_entries = [e for e in entries if e.get("action") == "bonjour_register"]
        self.assertTrue(len(register_entries) >= 1)
        self.assertEqual(register_entries[0]["outcome"], "skipped")
        self.assertEqual(register_entries[0]["reason"], "no_mdns_backend")

    @patch("aria_queue.bonjour.subprocess.Popen")
    @patch("aria_queue.bonjour._detect_backend", return_value="dns-sd")
    @patch("aria_queue.bonjour._dns_sd_path", return_value="/usr/bin/dns-sd")
    def test_http_service_registered_logs_action(
        self, _path: MagicMock, _backend: MagicMock, mock_popen: MagicMock,
    ) -> None:
        from aria_queue.bonjour import advertise_http_service
        from aria_queue.core import ensure_storage, load_action_log
        ensure_storage()
        proc = MagicMock()
        proc.poll.return_value = None  # process still running
        mock_popen.return_value = proc
        with advertise_http_service(port=8080):
            pass
        entries = load_action_log()
        register = [e for e in entries if e.get("action") == "bonjour_register" and e.get("outcome") == "changed"]
        deregister = [e for e in entries if e.get("action") == "bonjour_deregister"]
        self.assertTrue(len(register) >= 1)
        self.assertTrue(len(deregister) >= 1)


# ── routes/downloads.py — output path validation ──────────────────


class TestOutputPathValidation(unittest.TestCase):
    def test_rejects_absolute_path(self) -> None:
        from aria_queue.routes.downloads import _validate_output_path
        self.assertIsNotNone(_validate_output_path("/etc/passwd"))

    def test_rejects_dot_dot(self) -> None:
        from aria_queue.routes.downloads import _validate_output_path
        self.assertIsNotNone(_validate_output_path("../outside"))

    def test_rejects_hidden_directory(self) -> None:
        from aria_queue.routes.downloads import _validate_output_path
        self.assertIsNotNone(_validate_output_path(".hidden/file.txt"))

    def test_accepts_simple_relative(self) -> None:
        from aria_queue.routes.downloads import _validate_output_path
        self.assertIsNone(_validate_output_path("downloads/file.bin"))

    def test_accepts_empty(self) -> None:
        from aria_queue.routes.downloads import _validate_output_path
        self.assertIsNone(_validate_output_path(""))


if __name__ == "__main__":
    unittest.main()
