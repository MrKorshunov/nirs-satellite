"""Regression checks for the desktop launcher's safe, exact commands."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nirs_satellite.launcher_core import (
    build_plan, PROFILE_PHYSICAL, PROFILE_RESEARCH, PROFILE_TEST,
)


class LauncherPlans(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.python = self.root / ".venv" / "Scripts" / "python.exe"

    def make(self, profile=PROFILE_PHYSICAL, **overrides):
        kw = {
            "profile": profile, "name": "sample_123",
            "hours": 0.2 if profile == PROFILE_PHYSICAL else 4.0,
            "python_executable": self.python, "record_vizard": True,
            "root": self.root, "local_appdata": self.directory.name,
        }
        kw.update(overrides)
        return build_plan(**kw)

    def test_physical_uses_unified_two_target_basilisk_executor(self):
        plan = self.make()
        self.assertEqual(plan.argv[0], str(self.python))
        self.assertIn("experiments.mission_03.run", plan.argv)
        self.assertIn("--require-two-captures", plan.argv)
        self.assertNotIn("--power", plan.argv)  # Physical RW + power are built in
        self.assertIn("--viz-mode", plan.argv)
        self.assertIn("file", plan.argv)
        self.assertEqual(plan.result_dir, self.root / "results" / "sample_123")
        self.assertEqual(plan.vizard_file.name, "sample_123.bin")

    def test_research_uses_multiple_tasks_and_no_visualizer(self):
        plan = self.make(PROFILE_RESEARCH)
        self.assertIn("experiments.mission_02.run", plan.argv)
        self.assertNotIn("--actuator", plan.argv)
        self.assertNotIn("--power", plan.argv)
        self.assertIn("--step-s", plan.argv)
        self.assertIsNone(plan.vizard_file)

    def test_physical_recording_can_be_disabled(self):
        plan = self.make(record_vizard=False)
        self.assertIn("off", plan.argv)
        self.assertIsNone(plan.vizard_file)

    def test_stdlib_only_test_plan(self):
        plan = self.make(PROFILE_TEST, name="unused", hours=0, record_vizard=False)
        self.assertIn("unittest", plan.argv)
        self.assertIsNone(plan.result_dir)

    def test_no_shell_injection_or_unsafe_output_path(self):
        for name in ("../bad", "bad name", "x;exit", "досье", "A" * 49):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.make(name=name)

    def test_invalid_durations(self):
        for hours in (-1, 0, float("nan"), 0.01, 100):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                self.make(hours=hours)

    def test_unknown_profile_fails_closed(self):
        with self.assertRaises(ValueError):
            self.make(profile="external-commands")


if __name__ == "__main__":
    unittest.main()
