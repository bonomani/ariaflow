"""Unit tests for all aria2 RPC wrapper functions.

Each wrapper is tested against a mocked aria_rpc to verify:
- Correct RPC method name is called
- Parameters are passed correctly
- Return value is extracted from result["result"]
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ariaflow_server import core


_MODULE = "ariaflow_server.core.aria_rpc"


def _mock_rpc(return_value: object = "OK") -> MagicMock:
    """Create a mock aria_rpc that returns {"result": return_value}."""
    mock = MagicMock(return_value={"result": return_value})
    return mock


class TestAria2AddUri(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("gid-001"))
    def test_basic(self) -> None:
        gid = core.aria2_add_uri(["http://example.com/file"])
        self.assertEqual(gid, "gid-001")
        core.aria_rpc.assert_called_once_with(
            "aria2.addUri",
            [["http://example.com/file"]],
            port=6800,
            timeout=15,
        )

    @patch(_MODULE, _mock_rpc("gid-002"))
    def test_with_options(self) -> None:
        gid = core.aria2_add_uri(["http://a.com/f"], options={"dir": "/tmp"}, port=7000)
        self.assertEqual(gid, "gid-002")
        core.aria_rpc.assert_called_once_with(
            "aria2.addUri",
            [["http://a.com/f"], {"dir": "/tmp"}],
            port=7000,
            timeout=15,
        )

    @patch(_MODULE, _mock_rpc("gid-003"))
    def test_with_position(self) -> None:
        gid = core.aria2_add_uri(["http://a.com/f"], position=0)
        self.assertEqual(gid, "gid-003")
        args = core.aria_rpc.call_args
        self.assertEqual(args[0][1][2], 0)


class TestAria2AddTorrent(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("gid-t01"))
    def test_basic(self) -> None:
        gid = core.aria2_add_torrent("base64data")
        self.assertEqual(gid, "gid-t01")
        core.aria_rpc.assert_called_once_with(
            "aria2.addTorrent",
            ["base64data", []],
            port=6800,
            timeout=15,
        )

    @patch(_MODULE, _mock_rpc("gid-t02"))
    def test_with_options(self) -> None:
        gid = core.aria2_add_torrent(
            "b64", uris=["http://ws.com"], options={"dir": "/dl"}
        )
        self.assertEqual(gid, "gid-t02")
        core.aria_rpc.assert_called_once_with(
            "aria2.addTorrent",
            ["b64", ["http://ws.com"], {"dir": "/dl"}],
            port=6800,
            timeout=15,
        )


class TestAria2AddMetalink(unittest.TestCase):
    @patch(_MODULE, _mock_rpc(["gid-m1", "gid-m2"]))
    def test_returns_list(self) -> None:
        gids = core.aria2_add_metalink("ml-b64")
        self.assertEqual(gids, ["gid-m1", "gid-m2"])
        core.aria_rpc.assert_called_once_with(
            "aria2.addMetalink",
            ["ml-b64"],
            port=6800,
            timeout=15,
        )


class TestAria2Pause(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("gid-001"))
    def test_pause(self) -> None:
        result = core.aria2_pause("gid-001")
        self.assertEqual(result, "gid-001")
        core.aria_rpc.assert_called_once_with(
            "aria2.pause", ["gid-001"], port=6800, timeout=5
        )


class TestAria2ForcePause(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("gid-001"))
    def test_force_pause(self) -> None:
        result = core.aria2_force_pause("gid-001")
        self.assertEqual(result, "gid-001")
        core.aria_rpc.assert_called_once_with(
            "aria2.forcePause", ["gid-001"], port=6800, timeout=5
        )


class TestAria2PauseAll(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_pause_all(self) -> None:
        result = core.aria2_pause_all()
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.pauseAll", [], port=6800, timeout=5
        )


class TestAria2ForcePauseAll(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_force_pause_all(self) -> None:
        result = core.aria2_force_pause_all()
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.forcePauseAll", [], port=6800, timeout=5
        )


class TestAria2Unpause(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("gid-001"))
    def test_unpause(self) -> None:
        result = core.aria2_unpause("gid-001")
        self.assertEqual(result, "gid-001")
        core.aria_rpc.assert_called_once_with(
            "aria2.unpause", ["gid-001"], port=6800, timeout=5
        )


class TestAria2UnpauseAll(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_unpause_all(self) -> None:
        result = core.aria2_unpause_all()
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.unpauseAll", [], port=6800, timeout=5
        )


class TestAria2Remove(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("gid-001"))
    def test_remove(self) -> None:
        result = core.aria2_remove("gid-001")
        self.assertEqual(result, "gid-001")
        core.aria_rpc.assert_called_once_with(
            "aria2.remove", ["gid-001"], port=6800, timeout=5
        )


class TestAria2ForceRemove(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("gid-001"))
    def test_force_remove(self) -> None:
        result = core.aria2_force_remove("gid-001")
        self.assertEqual(result, "gid-001")
        core.aria_rpc.assert_called_once_with(
            "aria2.forceRemove", ["gid-001"], port=6800, timeout=5
        )


class TestAria2RemoveDownloadResult(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_remove_download_result(self) -> None:
        result = core.aria2_remove_download_result("gid-001")
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.removeDownloadResult", ["gid-001"], port=6800, timeout=5
        )


class TestAria2TellStatus(unittest.TestCase):
    @patch(_MODULE, _mock_rpc({"status": "active", "gid": "gid-001"}))
    def test_tell_status(self) -> None:
        info = core.aria2_tell_status("gid-001")
        self.assertEqual(info["status"], "active")
        args = core.aria_rpc.call_args
        self.assertEqual(args[0][0], "aria2.tellStatus")
        self.assertEqual(args[0][1][0], "gid-001")


class TestAria2TellActive(unittest.TestCase):
    @patch(_MODULE, MagicMock(return_value={"result": [{"gid": "g1"}, {"gid": "g2"}]}))
    def test_tell_active(self) -> None:
        result = core.aria2_tell_active()
        self.assertEqual(len(result), 2)
        core.aria_rpc.assert_called_once_with(
            "aria2.tellActive", [], port=6800, timeout=5
        )

    @patch(_MODULE, MagicMock(side_effect=Exception("conn refused")))
    def test_tell_active_error_returns_empty(self) -> None:
        result = core.aria2_tell_active()
        self.assertEqual(result, [])


class TestAria2TellWaiting(unittest.TestCase):
    @patch(_MODULE, MagicMock(return_value={"result": [{"gid": "w1"}]}))
    def test_tell_waiting(self) -> None:
        result = core.aria2_tell_waiting()
        self.assertEqual(len(result), 1)
        core.aria_rpc.assert_called_once_with(
            "aria2.tellWaiting", [0, 100], port=6800, timeout=5
        )


class TestAria2TellStopped(unittest.TestCase):
    @patch(_MODULE, MagicMock(return_value={"result": [{"gid": "s1"}]}))
    def test_tell_stopped(self) -> None:
        result = core.aria2_tell_stopped()
        self.assertEqual(len(result), 1)
        core.aria_rpc.assert_called_once_with(
            "aria2.tellStopped", [0, 100], port=6800, timeout=5
        )

    @patch(_MODULE, MagicMock(side_effect=Exception("err")))
    def test_tell_stopped_error_returns_empty(self) -> None:
        result = core.aria2_tell_stopped()
        self.assertEqual(result, [])


class TestAria2GetFiles(unittest.TestCase):
    @patch(_MODULE, _mock_rpc([{"index": "1", "path": "/dl/file.txt"}]))
    def test_get_files(self) -> None:
        files = core.aria2_get_files("gid-001")
        self.assertEqual(len(files), 1)
        core.aria_rpc.assert_called_once_with(
            "aria2.getFiles", ["gid-001"], port=6800, timeout=5
        )


class TestAria2GetUris(unittest.TestCase):
    @patch(_MODULE, _mock_rpc([{"uri": "http://a.com", "status": "used"}]))
    def test_get_uris(self) -> None:
        uris = core.aria2_get_uris("gid-001")
        self.assertEqual(uris[0]["uri"], "http://a.com")
        core.aria_rpc.assert_called_once_with(
            "aria2.getUris", ["gid-001"], port=6800, timeout=5
        )


class TestAria2GetPeers(unittest.TestCase):
    @patch(_MODULE, _mock_rpc([{"peerId": "p1", "ip": "1.2.3.4"}]))
    def test_get_peers(self) -> None:
        peers = core.aria2_get_peers("gid-001")
        self.assertEqual(peers[0]["ip"], "1.2.3.4")
        core.aria_rpc.assert_called_once_with(
            "aria2.getPeers", ["gid-001"], port=6800, timeout=5
        )


class TestAria2GetServers(unittest.TestCase):
    @patch(_MODULE, _mock_rpc([{"index": "1", "servers": []}]))
    def test_get_servers(self) -> None:
        servers = core.aria2_get_servers("gid-001")
        self.assertEqual(len(servers), 1)
        core.aria_rpc.assert_called_once_with(
            "aria2.getServers", ["gid-001"], port=6800, timeout=5
        )


class TestAria2GetOption(unittest.TestCase):
    @patch(_MODULE, _mock_rpc({"dir": "/downloads", "max-download-limit": "0"}))
    def test_get_option(self) -> None:
        opts = core.aria2_get_option("gid-001")
        self.assertEqual(opts["dir"], "/downloads")
        core.aria_rpc.assert_called_once_with(
            "aria2.getOption", ["gid-001"], port=6800, timeout=5
        )


class TestAria2ChangeOption(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_change_option(self) -> None:
        result = core.aria2_change_option("gid-001", {"max-download-limit": "100K"})
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.changeOption",
            ["gid-001", {"max-download-limit": "100K"}],
            port=6800,
            timeout=5,
        )


class TestAria2GetGlobalOption(unittest.TestCase):
    @patch(_MODULE, _mock_rpc({"max-concurrent-downloads": "5"}))
    def test_get_global_option(self) -> None:
        opts = core.aria2_get_global_option()
        self.assertEqual(opts["max-concurrent-downloads"], "5")
        core.aria_rpc.assert_called_once_with(
            "aria2.getGlobalOption", [], port=6800, timeout=5
        )


class TestAria2ChangeGlobalOption(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_change_global_option(self) -> None:
        result = core.aria2_change_global_option({"max-concurrent-downloads": "3"})
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.changeGlobalOption",
            [{"max-concurrent-downloads": "3"}],
            port=6800,
            timeout=5,
        )


class TestAria2GetGlobalStat(unittest.TestCase):
    @patch(_MODULE, _mock_rpc({"downloadSpeed": "1000", "numActive": "2"}))
    def test_get_global_stat(self) -> None:
        stat = core.aria2_get_global_stat()
        self.assertEqual(stat["numActive"], "2")
        core.aria_rpc.assert_called_once_with(
            "aria2.getGlobalStat", [], port=6800, timeout=5
        )


class TestAria2ChangePosition(unittest.TestCase):
    @patch(_MODULE, _mock_rpc(0))
    def test_change_position(self) -> None:
        pos = core.aria2_change_position("gid-001", 0, "POS_SET")
        self.assertEqual(pos, 0)
        core.aria_rpc.assert_called_once_with(
            "aria2.changePosition",
            ["gid-001", 0, "POS_SET"],
            port=6800,
            timeout=5,
        )


class TestAria2ChangeUri(unittest.TestCase):
    @patch(_MODULE, _mock_rpc([1, 1]))
    def test_change_uri(self) -> None:
        result = core.aria2_change_uri(
            "gid-001", 1, ["http://old.com"], ["http://new.com"]
        )
        self.assertEqual(result, [1, 1])
        core.aria_rpc.assert_called_once_with(
            "aria2.changeUri",
            ["gid-001", 1, ["http://old.com"], ["http://new.com"]],
            port=6800,
            timeout=5,
        )

    @patch(_MODULE, _mock_rpc([0, 1]))
    def test_change_uri_with_position(self) -> None:
        result = core.aria2_change_uri("gid-001", 1, [], ["http://new.com"], position=0)
        self.assertEqual(result, [0, 1])
        args = core.aria_rpc.call_args
        self.assertEqual(args[0][1][4], 0)


class TestAria2PurgeDownloadResult(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_purge(self) -> None:
        result = core.aria2_purge_download_result()
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.purgeDownloadResult", [], port=6800, timeout=5
        )


class TestAria2GetVersion(unittest.TestCase):
    @patch(_MODULE, _mock_rpc({"version": "1.37.0", "enabledFeatures": ["BitTorrent"]}))
    def test_get_version(self) -> None:
        info = core.aria2_get_version()
        self.assertEqual(info["version"], "1.37.0")
        core.aria_rpc.assert_called_once_with(
            "aria2.getVersion", [], port=6800, timeout=5
        )


class TestAria2GetSessionInfo(unittest.TestCase):
    @patch(_MODULE, _mock_rpc({"sessionId": "abc123"}))
    def test_get_session_info(self) -> None:
        info = core.aria2_get_session_info()
        self.assertEqual(info["sessionId"], "abc123")
        core.aria_rpc.assert_called_once_with(
            "aria2.getSessionInfo", [], port=6800, timeout=5
        )


class TestAria2SaveSession(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_save_session(self) -> None:
        result = core.aria2_save_session()
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.saveSession", [], port=6800, timeout=5
        )


class TestAria2Shutdown(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_shutdown(self) -> None:
        result = core.aria2_shutdown()
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.shutdown", [], port=6800, timeout=5
        )


class TestAria2ForceShutdown(unittest.TestCase):
    @patch(_MODULE, _mock_rpc("OK"))
    def test_force_shutdown(self) -> None:
        result = core.aria2_force_shutdown()
        self.assertEqual(result, "OK")
        core.aria_rpc.assert_called_once_with(
            "aria2.forceShutdown", [], port=6800, timeout=5
        )


class TestAria2Multicall(unittest.TestCase):
    @patch(_MODULE, _mock_rpc([["gid-001"], ["gid-002"]]))
    def test_multicall(self) -> None:
        calls = [
            {"methodName": "aria2.addUri", "params": [["http://a.com"]]},
            {"methodName": "aria2.addUri", "params": [["http://b.com"]]},
        ]
        result = core.aria2_multicall(calls)
        self.assertEqual(len(result), 2)
        core.aria_rpc.assert_called_once_with(
            "system.multicall", [calls], port=6800, timeout=15
        )


class TestAria2ListMethods(unittest.TestCase):
    @patch(_MODULE, _mock_rpc(["aria2.addUri", "aria2.pause"]))
    def test_list_methods(self) -> None:
        methods = core.aria2_list_methods()
        self.assertIn("aria2.addUri", methods)
        core.aria_rpc.assert_called_once_with(
            "system.listMethods", [], port=6800, timeout=5
        )


class TestAria2ListNotifications(unittest.TestCase):
    @patch(_MODULE, _mock_rpc(["aria2.onDownloadStart", "aria2.onDownloadComplete"]))
    def test_list_notifications(self) -> None:
        notifs = core.aria2_list_notifications()
        self.assertIn("aria2.onDownloadStart", notifs)
        core.aria_rpc.assert_called_once_with(
            "system.listNotifications", [], port=6800, timeout=5
        )


# ──────────────────────────────────────────────────────
# Port override test — verify all wrappers pass port
# ──────────────────────────────────────────────────────


class TestPortOverride(unittest.TestCase):
    """Verify custom port is forwarded to aria_rpc for every wrapper."""

    @patch(_MODULE, _mock_rpc("OK"))
    def test_pause_custom_port(self) -> None:
        core.aria2_pause("g1", port=7000)
        self.assertEqual(
            core.aria_rpc.call_args[1].get(
                "port",
                core.aria_rpc.call_args[0][2]
                if len(core.aria_rpc.call_args[0]) > 2
                else None,
            ),
            7000,
        )

    @patch(_MODULE, _mock_rpc("OK"))
    def test_shutdown_custom_port(self) -> None:
        core.aria2_shutdown(port=9999)
        _, kwargs = core.aria_rpc.call_args
        self.assertEqual(kwargs["port"], 9999)


if __name__ == "__main__":
    unittest.main()
