"""Independent CLI-setting tests: no Basilisk import is required."""
from __future__ import annotations
import argparse
import unittest

from experiments.ground_01.runtime import resolve_run


def options(**changes):
    defaults = dict(
        hours=None, days=None, orbits=None,
        physics_step_s=None, record_step_s=None, viz_step_s=None,
        mode=None, viz=False, speed=None, output_name="ground_01", payload=False,
    )
    defaults.update(changes)
    return argparse.Namespace(**defaults)


class GroundRuntimeSettingsTests(unittest.TestCase):
    scenario = {"step_s": 10.0, "number_of_orbits": 1.0}
    period = 5676.9780698

    def resolve(self, **kw):
        return resolve_run(options(**kw), self.scenario, self.period)

    def test_original_one_orbit_is_unchanged(self):
        x = self.resolve()
        self.assertEqual(x.mode, "batch")
        self.assertEqual(x.duration_s, self.period)
        self.assertEqual(x.physics_step_s, 10.0)
        self.assertEqual(x.record_step_s, 10.0)
        self.assertIsNone(x.viz_step_s)
        self.assertEqual(x.output_name, "ground_01")

    def test_legacy_viz_alias_preserved(self):
        x = self.resolve(viz=True)
        self.assertEqual(x.mode, "playback")
        self.assertEqual(x.viz_step_s, 10)

    def test_one_day_recording_and_visualization(self):
        x = self.resolve(days=1, mode="playback", record_step_s=30,
                         viz_step_s=60, output_name="ground_day")
        self.assertEqual(x.duration_s, 86400)
        self.assertEqual(x.record_step_s, 30)
        self.assertEqual(x.viz_step_s, 60)
        self.assertEqual(x.output_name, "ground_day")
        self.assertGreater(x.estimated_physics_steps, x.estimated_record_samples)
        self.assertGreater(x.estimated_record_samples, x.estimated_viz_frames)

    def test_live_speed_only_on_live(self):
        x = self.resolve(hours=2, mode="live", speed=50)
        self.assertEqual(x.live_speed_factor, 50)
        with self.assertRaisesRegex(ValueError, "only"):
            self.resolve(speed=50, mode="playback")

    def test_incorrect_record_multiple_rejected(self):
        with self.assertRaisesRegex(ValueError, "integer multiple"):
            self.resolve(record_step_s=15)

    def test_incorrect_viz_multiple_rejected(self):
        with self.assertRaisesRegex(ValueError, "integer multiple"):
            self.resolve(mode="playback", viz_step_s=15)

    def test_viz_setting_requires_mode(self):
        with self.assertRaises(ValueError):
            self.resolve(viz_step_s=20)

    def test_bad_output_name_and_zero_duration(self):
        with self.assertRaises(ValueError):
            self.resolve(output_name="../escape")
        with self.assertRaises(ValueError):
            self.resolve(hours=0)
        with self.assertRaises(ValueError):
            self.resolve(days=float("inf"))

    def test_too_many_steps_rejected(self):
        with self.assertRaisesRegex(ValueError, "safe sample limits"):
            self.resolve(days=1000)

    def test_long_run_payload_not_silently_repeated(self):
        with self.assertRaisesRegex(ValueError, "one-product"):
            self.resolve(days=1, payload=True)
        with self.assertRaisesRegex(ValueError, "one-product"):
            self.resolve(record_step_s=30, payload=True)

    def test_one_orbit_payload_is_compatible(self):
        self.assertEqual(self.resolve(payload=True).duration_s, self.period)

    def test_explicit_orbits(self):
        self.assertAlmostEqual(self.resolve(orbits=2).duration_s, self.period*2)

    def test_conflicting_mode_and_legacy_viz(self):
        with self.assertRaisesRegex(ValueError, "legacy alias"):
            self.resolve(mode="live", viz=True)


if __name__ == "__main__":
    unittest.main()
