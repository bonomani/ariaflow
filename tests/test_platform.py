"""Tests for cross-platform support (platform detection, service modules)."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock


class TestPlatformDetect(unittest.TestCase):
    def test_is_macos_on_darwin(self) -> None:
        with patch("sys.platform", "darwin"):
            from ariaflow_server.platform import detect

            self.assertTrue(detect.is_macos())
            self.assertFalse(detect.is_windows())
            self.assertFalse(detect.is_linux())

    def test_is_windows_on_win32(self) -> None:
        with patch("sys.platform", "win32"):
            from ariaflow_server.platform import detect

            self.assertFalse(detect.is_macos())
            self.assertTrue(detect.is_windows())
            self.assertFalse(detect.is_linux())

    def test_is_linux_on_linux(self) -> None:
        with patch("sys.platform", "linux"):
            from ariaflow_server.platform import detect

            self.assertFalse(detect.is_macos())
            self.assertFalse(detect.is_windows())
            self.assertTrue(detect.is_linux())


class TestPortalocker(unittest.TestCase):
    def test_storage_locked_acquires_and_releases(self) -> None:
        """Verify portalocker lock/unlock is called in storage_locked."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIAFLOW_DIR"] = tmp
            try:
                from ariaflow_server.storage import storage_locked

                with storage_locked():
                    pass  # should not raise
            finally:
                del os.environ["ARIAFLOW_DIR"]

    def test_storage_locked_releases_on_error(self) -> None:
        """Lock is released even when body raises."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ARIAFLOW_DIR"] = tmp
            try:
                from ariaflow_server.storage import storage_locked

                with self.assertRaises(ValueError):
                    with storage_locked():
                        raise ValueError("test")
            finally:
                del os.environ["ARIAFLOW_DIR"]


class TestWindowsModule(unittest.TestCase):
    def test_import_on_any_platform(self) -> None:
        from ariaflow_server.platform.windows import (
            task_scheduler_aria2_status,
            install_aria2_task,
            uninstall_aria2_task,
        )

        self.assertTrue(callable(task_scheduler_aria2_status))
        self.assertTrue(callable(install_aria2_task))
        self.assertTrue(callable(uninstall_aria2_task))

    def test_install_dry_run(self) -> None:
        from ariaflow_server.platform.windows import install_aria2_task

        commands = install_aria2_task(dry_run=True)
        self.assertIsInstance(commands, list)
        self.assertTrue(any("schtasks" in c for c in commands))

    def test_uninstall_dry_run(self) -> None:
        from ariaflow_server.platform.windows import uninstall_aria2_task

        commands = uninstall_aria2_task(dry_run=True)
        self.assertIsInstance(commands, list)
        self.assertTrue(any("schtasks" in c for c in commands))

    def test_status_when_schtasks_missing(self) -> None:
        from ariaflow_server.platform.windows import task_scheduler_aria2_status

        with patch("ariaflow_server.platform.windows.shutil.which", return_value=None):
            status = task_scheduler_aria2_status()
        self.assertFalse(status["loaded"])


class TestLinuxModule(unittest.TestCase):
    def test_import_on_any_platform(self) -> None:
        from ariaflow_server.platform.linux import (
            systemd_aria2_status,
            install_aria2_systemd,
            uninstall_aria2_systemd,
        )

        self.assertTrue(callable(systemd_aria2_status))
        self.assertTrue(callable(install_aria2_systemd))
        self.assertTrue(callable(uninstall_aria2_systemd))

    def test_install_dry_run(self) -> None:
        from ariaflow_server.platform.linux import install_aria2_systemd

        commands = install_aria2_systemd(dry_run=True)
        self.assertIsInstance(commands, list)
        self.assertTrue(any("systemctl" in c for c in commands))

    def test_uninstall_dry_run(self) -> None:
        from ariaflow_server.platform.linux import uninstall_aria2_systemd

        commands = uninstall_aria2_systemd(dry_run=True)
        self.assertIsInstance(commands, list)
        self.assertTrue(any("systemctl" in c for c in commands))

    def test_status_when_systemctl_missing(self) -> None:
        from ariaflow_server.platform.linux import systemd_aria2_status

        with patch("ariaflow_server.platform.linux.shutil.which", return_value=None):
            status = systemd_aria2_status()
        self.assertFalse(status["loaded"])

    def test_unit_file_content(self) -> None:
        from ariaflow_server.platform.linux import _build_unit
        from pathlib import Path

        unit = _build_unit("/usr/bin/aria2c", Path("/tmp/.aria2"), Path("/tmp/dl"))
        self.assertIn("[Unit]", unit)
        self.assertIn("[Service]", unit)
        self.assertIn("[Install]", unit)
        self.assertIn("/usr/bin/aria2c", unit)
        self.assertIn("--enable-rpc=true", unit)


class TestWSLDetection(unittest.TestCase):
    def test_is_wsl_true(self) -> None:
        from ariaflow_server.platform import detect

        with (
            patch("ariaflow_server.platform.detect.is_linux", return_value=True),
            patch(
                "ariaflow_server.platform.detect.Path.read_text",
                return_value="Linux version 6.6.87-microsoft-standard-WSL2",
            ),
        ):
            self.assertTrue(detect.is_wsl())

    def test_is_wsl_false_on_regular_linux(self) -> None:
        from ariaflow_server.platform import detect

        with (
            patch("ariaflow_server.platform.detect.is_linux", return_value=True),
            patch(
                "ariaflow_server.platform.detect.Path.read_text",
                return_value="Linux version 6.1.0-generic",
            ),
        ):
            self.assertFalse(detect.is_wsl())

    def test_is_wsl_false_on_macos(self) -> None:
        from ariaflow_server.platform import detect

        with patch("ariaflow_server.platform.detect.is_linux", return_value=False):
            self.assertFalse(detect.is_wsl())

    def test_is_wsl2_true(self) -> None:
        from ariaflow_server.platform import detect

        with (
            patch("ariaflow_server.platform.detect.is_wsl", return_value=True),
            patch(
                "ariaflow_server.platform.detect.Path.read_text",
                return_value="Linux version 6.6.87-microsoft-standard-WSL2",
            ),
        ):
            self.assertTrue(detect.is_wsl2())

    def test_is_wsl2_false_on_wsl1(self) -> None:
        from ariaflow_server.platform import detect

        with (
            patch("ariaflow_server.platform.detect.is_wsl", return_value=True),
            patch(
                "ariaflow_server.platform.detect.Path.read_text",
                return_value="Linux version 4.4.0-microsoft-standard",
            ),
        ):
            self.assertFalse(detect.is_wsl2())

    def test_is_wsl2_false_on_non_wsl(self) -> None:
        from ariaflow_server.platform import detect

        with patch("ariaflow_server.platform.detect.is_wsl", return_value=False):
            self.assertFalse(detect.is_wsl2())

    def test_is_nated_true_on_wsl2(self) -> None:
        from ariaflow_server.platform import detect

        with patch("ariaflow_server.platform.detect.is_wsl2", return_value=True):
            self.assertTrue(detect.is_nated())

    def test_is_nated_false_on_non_wsl2(self) -> None:
        from ariaflow_server.platform import detect

        with patch("ariaflow_server.platform.detect.is_wsl2", return_value=False):
            self.assertFalse(detect.is_nated())

    def test_default_downloads_dir_non_wsl(self) -> None:
        from ariaflow_server.platform.detect import default_downloads_dir

        with patch("ariaflow_server.platform.detect.is_wsl", return_value=False):
            result = default_downloads_dir()
        from pathlib import Path

        self.assertEqual(result, Path.home() / "Downloads")

    def test_default_downloads_dir_wsl(self) -> None:
        from ariaflow_server.platform.detect import default_downloads_dir

        with (
            patch("ariaflow_server.platform.detect.is_wsl", return_value=True),
            patch(
                "ariaflow_server.platform.detect.wsl_windows_downloads",
                return_value=MagicMock(spec=True),
            ) as mock_wsl,
        ):
            mock_wsl.return_value = "/mnt/c/Users/testuser/Downloads"
            result = default_downloads_dir()
        self.assertEqual(str(result), "/mnt/c/Users/testuser/Downloads")


if __name__ == "__main__":
    unittest.main()
