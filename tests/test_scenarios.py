"""End-to-end scenario tests.

Each test simulates a realistic user workflow through the API,
verifying state consistency across multiple operations.
"""

from __future__ import annotations

import socket
import threading
import time
import unittest
from unittest.mock import patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import APIServerTestCase, request_json as _req

from aria_queue.core import load_queue, save_queue


ScenarioBase = APIServerTestCase


# ═══════════════════════════════════════════════════════
# Scenario 1: Normal download lifecycle
# ═══════════════════════════════════════════════════════


class TestScenarioNormalDownload(ScenarioBase):
    """User adds URLs, starts a run, downloads complete, queue empties."""

    def test_full_download_lifecycle(self) -> None:
        base = self.base

        # 1. Check system is idle
        _, status, _ = _req(f"{base}/api/status")
        self.assertFalse(status["state"]["running"])

        # 2. Run preflight
        with (
            patch(
                "aria_queue.webapp.preflight",
                return_value={
                    "contract": "UCC",
                    "version": "2.0",
                    "gates": [
                        {
                            "name": "aria2_available",
                            "satisfied": True,
                            "blocking": "hard",
                        },
                        {
                            "name": "queue_readable",
                            "satisfied": True,
                            "blocking": "hard",
                        },
                    ],
                    "preferences": [],
                    "policies": [],
                    "warnings": [],
                    "hard_failures": [],
                    "status": "pass",
                    "exit_code": 0,
                },
            ),
            patch("aria_queue.webapp.aria2_status", return_value={"reachable": True}),
            patch("aria_queue.webapp.aria2_current_bandwidth", return_value={}),
        ):
            _, preflight, _ = _req(f"{base}/api/scheduler/preflight", "POST")
        self.assertEqual(preflight["status"], "pass")
        self.assertTrue(preflight["gates"][0]["satisfied"])

        # 3. Add multiple URLs
        _, added, _ = _req(
            f"{base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": "https://example.com/model-7b.gguf"},
                    {"url": "https://example.com/model-13b.gguf"},
                    {"url": "https://example.com/model-70b.gguf"},
                ]
            },
        )
        self.assertEqual(added["count"], 3)

        # 4. Verify status shows 3 queued
        _, status, _ = _req(f"{base}/api/status")
        self.assertEqual(status["summary"]["queued"], 3)
        self.assertEqual(status["summary"]["total"], 3)

        # 5. Scheduler is auto-started — simulate downloads completing
        items = load_queue()
        for item in items:
            item["status"] = "complete"
            item["post_action"] = {"status": "not defined yet"}
        save_queue(items)

        # Wait for status cache to expire (2s TTL)
        time.sleep(2.1)

        # 6. Verify all done
        _, status, _ = _req(f"{base}/api/status")
        self.assertEqual(status["summary"]["complete"], 3)

        # 7. Check action log recorded the workflow
        _, log, _ = _req(f"{base}/api/log?limit=20")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("add", actions)
        self.assertIn("preflight", actions)


# ═══════════════════════════════════════════════════════
# Scenario 2: Pause, resume, and cancel mid-download
# ═══════════════════════════════════════════════════════


class TestScenarioPauseResumeCancel(ScenarioBase):
    """User pauses items, resumes some, removes others."""

    def test_pause_resume_remove_workflow(self) -> None:
        base = self.base

        # Add 3 items
        _, added, _ = _req(
            f"{base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": "https://example.com/file-a.bin"},
                    {"url": "https://example.com/file-b.bin"},
                    {"url": "https://example.com/file-c.bin"},
                ]
            },
        )
        id_a, id_b, id_c = [item["id"] for item in added["added"]]

        # Pause all 3
        for item_id in (id_a, id_b, id_c):
            code, body, _ = _req(f"{base}/api/downloads/{item_id}/pause", "POST")
            self.assertEqual(code, 200)

        # Verify all paused in status
        _, status, _ = _req(f"{base}/api/status")
        paused_count = sum(1 for item in status["items"] if item["status"] == "paused")
        self.assertEqual(paused_count, 3)

        # Resume only A
        _, resumed, _ = _req(f"{base}/api/downloads/{id_a}/resume", "POST")
        self.assertEqual(resumed["item"]["status"], "queued")

        # Remove B
        _, removed, _ = _req(f"{base}/api/downloads/{id_b}/remove", "POST")
        self.assertTrue(removed["removed"])

        # C stays paused, A is queued, B is gone
        _, status, _ = _req(f"{base}/api/status")
        items_by_id = {item["id"]: item for item in status["items"]}
        self.assertEqual(items_by_id[id_a]["status"], "queued")
        self.assertNotIn(id_b, items_by_id)
        self.assertEqual(items_by_id[id_c]["status"], "paused")

        # Try to pause A again → should work (it's queued)
        _, paused, _ = _req(f"{base}/api/downloads/{id_a}/pause", "POST")
        self.assertEqual(paused["item"]["status"], "paused")


# ═══════════════════════════════════════════════════════
# Scenario 3: Error handling and retry
# ═══════════════════════════════════════════════════════


class TestScenarioErrorRetry(ScenarioBase):
    """Downloads fail, user retries some, removes others."""

    def test_error_retry_workflow(self) -> None:
        base = self.base

        # Add items
        _, added, _ = _req(
            f"{base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": "https://example.com/fail-1.bin"},
                    {"url": "https://example.com/fail-2.bin"},
                ]
            },
        )
        id_1, id_2 = [item["id"] for item in added["added"]]

        # Simulate both erroring out
        items = load_queue()
        for item in items:
            if item["id"] in (id_1, id_2):
                item["status"] = "error"
                item["error_code"] = "5"
                item["error_message"] = "connection timeout"
                item["gid"] = f"gid-dead-{item['id'][:8]}"
        save_queue(items)

        # Verify errors in status
        _, status, _ = _req(f"{base}/api/status")
        errors = [item for item in status["items"] if item["status"] == "error"]
        self.assertEqual(len(errors), 2)

        # Retry first one
        _, retried, _ = _req(f"{base}/api/downloads/{id_1}/retry", "POST")
        self.assertEqual(retried["item"]["status"], "queued")
        self.assertNotIn("error_code", retried["item"])
        self.assertNotIn("gid", retried["item"])

        # Remove second one
        _req(f"{base}/api/downloads/{id_2}/remove", "POST")

        # Final state: 1 queued, 0 errors
        _, status, _ = _req(f"{base}/api/status")
        self.assertEqual(status["summary"]["queued"], 1)
        self.assertEqual(status["summary"].get("error", 0), 0)

        # Can't retry a queued item
        code, body, _ = _req(f"{base}/api/downloads/{id_1}/retry", "POST")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"], "invalid_state")


# ═══════════════════════════════════════════════════════
# Scenario 4: Bandwidth probe and configuration
# ═══════════════════════════════════════════════════════


class TestScenarioBandwidth(ScenarioBase):
    """User configures bandwidth policy and runs manual probes."""

    def test_bandwidth_config_and_probe(self) -> None:
        base = self.base

        # Check defaults
        _, bw, _ = _req(f"{base}/api/bandwidth")
        self.assertEqual(bw["config"]["down_free_percent"], 20)
        self.assertEqual(bw["config"]["up_free_percent"], 50)

        # Modify bandwidth config via declaration
        _, decl, _ = _req(f"{base}/api/declaration")
        for pref in decl["uic"]["preferences"]:
            if pref["name"] == "bandwidth_down_free_percent":
                pref["value"] = 30
            if pref["name"] == "bandwidth_down_free_absolute_mbps":
                pref["value"] = 5
            if pref["name"] == "bandwidth_up_free_percent":
                pref["value"] = 70
        _req(f"{base}/api/declaration", "POST", decl)

        # Verify config changed
        _, bw, _ = _req(f"{base}/api/bandwidth")
        self.assertEqual(bw["config"]["down_free_percent"], 30)
        self.assertEqual(bw["config"]["down_free_absolute_mbps"], 5)
        self.assertEqual(bw["config"]["up_free_percent"], 70)

        # Run manual probe
        probe_result = {
            "source": "networkquality",
            "reason": "probe_complete",
            "downlink_mbps": 100.0,
            "uplink_mbps": 25.0,
            "cap_mbps": 70.0,
            "cap_bytes_per_sec": 8750000,
            "interface_name": "en0",
            "responsiveness_rpm": 1200.0,
        }
        with (
            patch("aria_queue.core.probe_bandwidth", return_value=probe_result),
            patch("aria_queue.core.aria2_set_max_overall_download_limit"),
        ):
            _, probed, _ = _req(f"{base}/api/bandwidth/probe", "POST")

        self.assertTrue(probed["ok"])
        self.assertEqual(probed["downlink_mbps"], 100.0)
        self.assertEqual(probed["uplink_mbps"], 25.0)
        self.assertIsNotNone(probed["down_cap_mbps"])
        self.assertIsNotNone(probed["up_cap_mbps"])
        # 30% free of 100 = 70 cap, but also 5 Mbps absolute free = 95 cap
        # stricter wins: 70 Mbps
        self.assertLessEqual(probed["down_cap_mbps"], 70.0)
        # 70% free of 25 = 7.5 cap
        self.assertLessEqual(probed["up_cap_mbps"], 7.5)

        # Bandwidth status should now reflect probe
        _, bw, _ = _req(f"{base}/api/bandwidth")
        self.assertEqual(bw["downlink_mbps"], 100.0)
        self.assertEqual(bw["uplink_mbps"], 25.0)
        self.assertEqual(bw["interface"], "en0")


# ═══════════════════════════════════════════════════════
# Scenario 6: Torrent file selection
# ═══════════════════════════════════════════════════════


class TestScenarioTorrentFileSelection(ScenarioBase):
    """User adds a torrent, lists files, selects specific ones."""

    def test_torrent_file_pick_workflow(self) -> None:
        base = self.base

        # Add torrent URL
        _, added, _ = _req(
            f"{base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": "https://example.com/linux.torrent"}],
            },
        )
        item_id = added["added"][0]["id"]

        # Simulate aria2 having metadata (gid assigned, paused for selection)
        items = load_queue()
        for item in items:
            if item["id"] == item_id:
                item["gid"] = "gid-torrent-1"
                item["status"] = "paused"
        save_queue(items)

        # List files
        files = [
            {
                "index": "1",
                "path": "/downloads/ubuntu.iso",
                "length": "3200000000",
                "selected": "true",
            },
            {
                "index": "2",
                "path": "/downloads/readme.txt",
                "length": "1024",
                "selected": "true",
            },
            {
                "index": "3",
                "path": "/downloads/checksums.md5",
                "length": "256",
                "selected": "true",
            },
        ]
        with patch("aria_queue.core.aria_rpc", return_value={"result": files}):
            _, file_list, _ = _req(f"{base}/api/downloads/{item_id}/files")
        self.assertEqual(len(file_list["files"]), 3)

        # Select only the ISO
        with patch("aria_queue.core.aria_rpc") as rpc:
            _, selected, _ = _req(
                f"{base}/api/downloads/{item_id}/files",
                "POST",
                {"select": [1]},
            )
        self.assertTrue(selected["ok"])
        self.assertEqual(selected["selected"], [1])
        rpc.assert_any_call(
            "aria2.changeOption",
            ["gid-torrent-1", {"select-file": "1"}],
            port=6800,
            timeout=5,
        )

        # Item should now be downloading
        _, status, _ = _req(f"{base}/api/status")
        item = next(i for i in status["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "active")


# ═══════════════════════════════════════════════════════
# Scenario 7: aria2 options management
# ═══════════════════════════════════════════════════════


class TestScenarioAria2Options(ScenarioBase):
    """User adjusts aria2 runtime settings via safe proxy."""

    def test_options_management(self) -> None:
        base = self.base

        # Try unsafe option → rejected
        code, body, _ = _req(
            f"{base}/api/aria2/change_global_option",
            "POST",
            {
                "dir": "/tmp/evil",
                "enable-rpc": "false",
            },
        )
        self.assertEqual(code, 400)
        self.assertIn("dir", body["message"])
        self.assertIn("enable-rpc", body["message"])

        # Apply safe options
        with (
            patch("aria_queue.core.aria_rpc"),
            patch("aria_queue.core.aria2_current_global_options", return_value={}),
        ):
            _, result, _ = _req(
                f"{base}/api/aria2/change_global_option",
                "POST",
                {
                    "max-concurrent-downloads": "5",
                    "split": "4",
                },
            )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["applied"]), 2)

        # Verify action was logged
        _, log, _ = _req(f"{base}/api/log?limit=5")
        actions = [e.get("action") for e in log["items"]]
        self.assertIn("change_options", actions)


# Scenario 8 removed — scheduler auto-starts, no start endpoint


# ═══════════════════════════════════════════════════════
# Scenario 9: Duplicate URL handling
# ═══════════════════════════════════════════════════════


class TestScenarioDuplicateHandling(ScenarioBase):
    """Adding the same URL multiple times deduplicates."""

    def test_duplicate_urls(self) -> None:
        base = self.base
        url = f"https://example.com/dedup-{time.time()}.bin"

        # Add once
        _, first, _ = _req(
            f"{base}/api/downloads/add", "POST", {"items": [{"url": url}]}
        )
        first_id = first["added"][0]["id"]

        # Add same URL again
        _, second, _ = _req(
            f"{base}/api/downloads/add", "POST", {"items": [{"url": url}]}
        )
        second_id = second["added"][0]["id"]

        # Same item returned
        self.assertEqual(first_id, second_id)

        # Only 1 item in queue for this URL
        _, status, _ = _req(f"{base}/api/status")
        matching = [item for item in status["items"] if item["url"] == url]
        self.assertEqual(len(matching), 1)


# ═══════════════════════════════════════════════════════
# Scenario 10: Frontend consistency (ETag + revision)
# ═══════════════════════════════════════════════════════


class TestScenarioFrontendConsistency(ScenarioBase):
    """Frontend uses ETag and revision to stay consistent."""

    def test_etag_caching_workflow(self) -> None:
        base = self.base

        # First poll → get ETag
        _, body1, hdrs1 = _req(f"{base}/api/status")
        etag1 = hdrs1.get("ETag", "")
        body1["_rev"]  # ensure key exists
        self.assertTrue(len(etag1) > 0)

        # Same state → 304
        code, _, _ = _req(f"{base}/api/status", headers={"If-None-Match": etag1})
        self.assertEqual(code, 304)

        # Mutate state
        _req(
            f"{base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": f"https://example.com/etag-change-{time.time()}.bin"}
                ],
            },
        )

        # New poll → different ETag (state mutated)
        _, body2, hdrs2 = _req(f"{base}/api/status")
        etag2 = hdrs2.get("ETag", "")
        self.assertNotEqual(etag1, etag2)
        # Revision is still a positive integer
        self.assertGreater(body2["_rev"], 0)

    def test_schema_version_detection(self) -> None:
        base = self.base
        _, body, hdrs = _req(f"{base}/api/status")
        self.assertEqual(body["_schema"], "2")
        self.assertEqual(hdrs.get("X-Schema-Version"), "2")
        self.assertEqual(body["ariaflow"]["schema_version"], "2")


# ═══════════════════════════════════════════════════════
# Scenario 11: SSE real-time updates
# ═══════════════════════════════════════════════════════


class TestScenarioSSE(ScenarioBase):
    """Frontend connects to SSE and receives state change events."""

    def test_sse_receives_state_change(self) -> None:
        base = self.base

        # Connect to SSE
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        sock.settimeout(5)
        sock.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")

        # Read connected event
        data = b""
        while b"connected" not in data:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk

        self.assertIn(b"event: connected", data)

        # Trigger a state change via add
        _req(
            f"{base}/api/downloads/add",
            "POST",
            {
                "items": [{"url": f"https://example.com/sse-{time.time()}.bin"}],
            },
        )

        # Read state_changed event
        try:
            while b"state_changed" not in data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        finally:
            sock.close()

        text = data.decode("utf-8", errors="replace")
        self.assertIn("event: state_changed", text)
        self.assertIn('"_rev"', text)


# ═══════════════════════════════════════════════════════
# Scenario 12: Full lifecycle install → status → uninstall
# ═══════════════════════════════════════════════════════


class TestScenarioLifecycle(ScenarioBase):
    """Check lifecycle status and run install/uninstall actions."""

    def test_lifecycle_check_and_action(self) -> None:
        base = self.base

        # Check lifecycle status
        _, lifecycle, _ = _req(f"{base}/api/lifecycle")
        self.assertIn("ariaflow", lifecycle)
        self.assertIn("aria2", lifecycle)
        self.assertIn("networkquality", lifecycle)

        # Install (mocked)
        with (
            patch("aria_queue.routes.lifecycle.is_macos", return_value=True),
            patch(
                "aria_queue.routes.lifecycle.homebrew_install_ariaflow_server",
                return_value=["brew install ariaflow"],
            ),
        ):
            _, result, _ = _req(
                f"{base}/api/lifecycle/ariaflow-server/install",
                "POST",
                {
                    "target": "ariaflow-server",
                    "action": "install",
                },
            )
        self.assertTrue(result["ok"])

        # Uninstall (mocked)
        with (
            patch("aria_queue.routes.lifecycle.is_macos", return_value=True),
            patch(
                "aria_queue.routes.lifecycle.homebrew_uninstall_ariaflow_server",
                return_value=["brew uninstall ariaflow"],
            ),
        ):
            _, result, _ = _req(
                f"{base}/api/lifecycle/ariaflow-server/uninstall",
                "POST",
                {},
            )
        self.assertTrue(result["ok"])


# ═══════════════════════════════════════════════════════
# Scenario 13: Declaration roundtrip with custom preferences
# ═══════════════════════════════════════════════════════


class TestScenarioDeclarationRoundtrip(ScenarioBase):
    """Modify declaration preferences and verify persistence."""

    def test_declaration_custom_prefs(self) -> None:
        base = self.base

        # Get current declaration
        _, decl, _ = _req(f"{base}/api/declaration")
        self.assertEqual(decl["meta"]["contract"], "UCC")

        # Add a custom preference
        decl["uic"]["preferences"].append(
            {
                "name": "custom_test_pref",
                "value": "hello",
                "options": ["hello", "world"],
                "rationale": "test scenario",
            }
        )

        # Save
        _, saved, _ = _req(f"{base}/api/declaration", "POST", decl)
        self.assertTrue(saved["saved"])

        # Reload and verify
        _, reloaded, _ = _req(f"{base}/api/declaration")
        names = [p["name"] for p in reloaded["uic"]["preferences"]]
        self.assertIn("custom_test_pref", names)
        custom = next(
            p for p in reloaded["uic"]["preferences"] if p["name"] == "custom_test_pref"
        )
        self.assertEqual(custom["value"], "hello")

        # Modify it
        for pref in reloaded["uic"]["preferences"]:
            if pref["name"] == "custom_test_pref":
                pref["value"] = "world"
        _req(f"{base}/api/declaration", "POST", reloaded)

        # Verify change persisted
        _, final, _ = _req(f"{base}/api/declaration")
        custom = next(
            p for p in final["uic"]["preferences"] if p["name"] == "custom_test_pref"
        )
        self.assertEqual(custom["value"], "world")


# ═══════════════════════════════════════════════════════
# Scenario 14: Concurrent operations
# ═══════════════════════════════════════════════════════


class TestScenarioConcurrent(ScenarioBase):
    """Multiple simultaneous operations don't corrupt state."""

    def test_concurrent_adds(self) -> None:
        base = self.base
        results: list[tuple[int, dict]] = []

        def add_item(i: int) -> None:
            code, body, _ = _req(
                f"{base}/api/downloads/add",
                "POST",
                {
                    "items": [
                        {"url": f"https://example.com/concurrent-{i}-{time.time()}.bin"}
                    ],
                },
            )
            results.append((code, body))

        threads = [threading.Thread(target=add_item, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(results), 10)
        for code, body in results:
            self.assertEqual(code, 200)
            self.assertTrue(body["ok"])

        # All items present
        _, status, _ = _req(f"{base}/api/status")
        self.assertGreaterEqual(status["summary"]["total"], 10)

    def test_concurrent_pause_resume(self) -> None:
        base = self.base

        # Add items
        _, added, _ = _req(
            f"{base}/api/downloads/add",
            "POST",
            {
                "items": [
                    {"url": f"https://example.com/conc-pr-{i}-{time.time()}.bin"}
                    for i in range(5)
                ]
            },
        )
        ids = [item["id"] for item in added["added"]]

        # Pause all concurrently
        results: list[int] = []

        def pause(item_id: str) -> None:
            code, _, _ = _req(f"{base}/api/downloads/{item_id}/pause", "POST")
            results.append(code)

        threads = [threading.Thread(target=pause, args=(item_id,)) for item_id in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(results), 5)
        self.assertTrue(all(code == 200 for code in results))


if __name__ == "__main__":
    unittest.main()
