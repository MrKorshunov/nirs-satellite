"""Central input catalog and safe JSON editing regression tests."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nirs_satellite.input_paths import FILES, INPUT_ROOT, input_path, load_input
from nirs_satellite.input_editor import save_input, validate_json_text


class InputRegistryTests(unittest.TestCase):
    def test_all_canonical_input_files_exist(self):
        self.assertGreaterEqual(len(FILES), 9)
        for name, (relative, label) in FILES.items():
            with self.subTest(name=name):
                self.assertTrue(label)
                self.assertTrue(input_path(name).is_file())
                self.assertTrue(input_path(name).is_relative_to(INPUT_ROOT))
                self.assertTrue(relative.endswith(".json"))
                self.assertTrue(load_input(name)["provenance"].startswith("SYNTHETIC"))

    def test_earth_orbit_link_is_single_source(self):
        ground = load_input("earth_target")
        orbit = (input_path("earth_target").parent /
                 ground["orbit_config_path"]).resolve()
        self.assertEqual(orbit, input_path("orbit").resolve())

    def test_unlisted_path_is_rejected(self):
        with self.assertRaises(KeyError):
            input_path("../README.md")

    def test_json_editor_checks_schema_markers(self):
        with self.assertRaises(ValueError):
            validate_json_text('["a"]')
        with self.assertRaises(ValueError):
            validate_json_text('{"scenario_id":"x","provenance":"REAL"}')
        with self.assertRaises(ValueError):
            validate_json_text('{"provenance":"SYNTHETIC","scenario_id":""}')
        self.assertEqual(
            validate_json_text('{"provenance":"SYNTHETIC TEST","scenario_id":"x"}')["scenario_id"],
            "x",
        )

    def test_editor_creates_backup_and_preserves_data(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            before = {"scenario_id":"test","provenance":"SYNTHETIC","number":1}
            after = {**before, "number":5}
            path.write_text(json.dumps(before),encoding="utf-8")
            with patch("nirs_satellite.input_editor.input_path",return_value=path):
                save_input("orbit", json.dumps(after))
            saved = json.loads(path.read_text(encoding="utf-8"))
            old = json.loads((Path(tmp)/"test.json.bak").read_text(encoding="utf-8"))
            self.assertEqual(saved["number"],5)
            self.assertEqual(old["number"],1)

    def test_invalid_editor_does_not_modify_original(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            path.write_text('{"scenario_id":"x","provenance":"SYNTHETIC"}', encoding="utf-8")
            with patch("nirs_satellite.input_editor.input_path",return_value=path):
                with self.assertRaises(ValueError):
                    save_input("orbit",'["invalid"]')
            self.assertFalse(path.with_suffix(".json.bak").exists())


if __name__ == "__main__":
    unittest.main()
