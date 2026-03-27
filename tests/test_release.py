from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "publish.py"
SPEC = importlib.util.spec_from_file_location("release_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
release_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_script)


class ReleaseScriptTests(unittest.TestCase):
    def test_parse_version_accepts_alpha_shape(self) -> None:
        self.assertEqual(release_script.parse_version("0.1.1a45"), (0, 1, 1, 45))

    def test_version_to_tag_requires_stable_semver(self) -> None:
        with self.assertRaises(SystemExit):
            release_script.version_to_tag("0.1.1a45")

    def test_version_to_tag_uses_stable_tag_shape(self) -> None:
        self.assertEqual(release_script.version_to_tag("0.1.2"), "v0.1.2")

    def test_build_plan_marks_manual_fallback_role(self) -> None:
        plan = release_script.build_plan(
            action="release",
            current="0.1.1",
            next_version="0.1.2",
            tag="v0.1.2",
            run_tests=True,
            allow_dirty=False,
        )
        self.assertIn("explicit release dispatch helper", plan[0])
        self.assertIn("requested version: 0.1.2", plan)

    def test_build_plan_without_version_is_rebase_safe_push_helper(self) -> None:
        plan = release_script.build_plan(
            action="push",
            current="0.1.1",
            next_version=None,
            tag=None,
            run_tests=False,
            allow_dirty=False,
        )
        self.assertIn("rebase-safe main publish helper", plan[0])
        self.assertIn("requested version: none", plan)


if __name__ == "__main__":
    unittest.main()
