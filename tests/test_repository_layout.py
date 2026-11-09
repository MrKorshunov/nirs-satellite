"""The user-facing structure must match the runtime's single input registry."""
from __future__ import annotations

from pathlib import Path
import unittest

from nirs_satellite.input_paths import FILES, ROOT, input_path


class RepositoryLayoutTests(unittest.TestCase):
    def test_main_launchers_exist(self):
        for file in ("START_NIRS.cmd", "SETUP_NIRS.cmd", "CHECK_NIRS.cmd"):
            with self.subTest(file=file):
                self.assertTrue((ROOT / file).is_file())

    def test_curated_documentation_exists(self):
        for file in (
            "README.md", "docs/START_HERE.md", "docs/CODE_MAP.md",
            "docs/INPUT_DATA.md", "docs/WHAT_IS_MISSING.md",
            "docs/COMPARISON_BASILISK.md", "docs/WINDOWS_GUI_GUIDE.md",
            "docs/history/README.md", "archive/README.md", "inputs/README.md",
        ):
            with self.subTest(file=file):
                self.assertTrue((ROOT / file).is_file())

    def test_every_input_has_one_config_location(self):
        for key in FILES:
            with self.subTest(key=key):
                path = input_path(key)
                self.assertEqual(path.parent.parent.name, "inputs")
                self.assertTrue(path.is_file())

    def test_no_shadow_parameter_copies_in_experiments(self):
        self.assertEqual(list((ROOT / "experiments").glob("*/config*.json")), [])

    def test_original_fifo_edf_is_archived(self):
        root = ROOT / "archive" / "v01"
        for file in ("main.py", "explain.py", "model.py", "engine.py", "demo.json"):
            self.assertTrue((root / file).is_file())


if __name__ == "__main__":
    unittest.main()
