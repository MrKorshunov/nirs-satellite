"""Runtime planning and input provenance tests; no Basilisk installation needed."""
import json
import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from experiments.ground_01.run_settings import build_plan
from experiments.ground_01.run_reporting import write_run_explanation


BASE = {"default_orbits": 1.0, "orbit_period_s": 5676.978,
        "default_step_s": 10.0}


class RuntimeSettingsTests(unittest.TestCase):
    def test_default_keeps_old_one_orbit(self):
        plan = build_plan(**BASE)
        self.assertAlmostEqual(plan.horizon_s, 5676.978)
        self.assertEqual(plan.expected_samples, 568)
        self.assertEqual(plan.viz_mode, "off")
        self.assertEqual(plan.output_name, "ground_01")

    def test_one_day_and_seven_days(self):
        day = build_plan(**BASE, duration_days=1, output_name="ground_day")
        week = build_plan(**BASE, duration_days=7, output_name="ground_week")
        self.assertEqual(day.horizon_s, 86400)
        self.assertEqual(day.expected_samples, 8641)
        self.assertEqual(week.expected_samples, 60481)
        self.assertEqual(week.duration_source, "days")

    def test_hours_and_orbits(self):
        one_hour = build_plan(**BASE, duration_hours=1)
        four_orbits = build_plan(**BASE, orbits=4)
        self.assertEqual(one_hour.expected_samples, 361)
        self.assertAlmostEqual(four_orbits.horizon_s, 4 * BASE["orbit_period_s"])

    def test_live_different_from_recording(self):
        live = build_plan(**BASE, duration_hours=2,
                          viz_mode="live", viz_step_s=30,
                          speed=50, live_port=5556)
        self.assertEqual(live.live_speed, 50)
        self.assertEqual(live.expected_samples, 721)
        self.assertEqual(live.expected_viz_frames, 241)
        self.assertEqual(live.live_port, 5556)
        recorded = build_plan(**BASE, duration_hours=2,
                              viz_mode="file", viz_step_s=60)
        self.assertIsNone(recorded.live_speed)
        self.assertEqual(recorded.expected_viz_frames, 121)

    def test_viz_backward_compatibility(self):
        self.assertEqual(build_plan(**BASE, legacy_viz=True).viz_mode, "file")

    def test_reject_invalid_duration_and_stride(self):
        cases = [
            {"duration_hours": 1, "orbits": 2},
            {"duration_days": -1},
            {"duration_hours": float("nan")},
            {"duration_hours": 0.00001},
            {"step_s": 0},
            {"viz_mode": "file", "viz_step_s": 15},
            {"viz_mode": "file", "viz_step_s": 9},
            {"viz_mode": "off", "viz_step_s": 20},
            {"viz_mode": "file", "speed": 20},
            {"viz_mode": "live", "speed": -5},
            {"viz_mode": "live", "speed": float("inf")},
            {"viz_mode": "broken"},
            {"viz_mode": "file", "legacy_viz": True},
            {"live_port": 1},
            {"output_name": "../../unsafe"},
            {"output_name": "НИР"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_plan(**BASE, **kwargs)

    def test_large_guard_requires_opt_in(self):
        with self.assertRaisesRegex(ValueError, "allow-large-run"):
            build_plan(**BASE, duration_days=14)
        self.assertGreater(
            build_plan(**BASE, duration_days=14, allow_large_run=True).expected_samples,
            100000,
        )

    def test_input_provenance_in_explained_output(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / "input.json"
            cfg.write_text('{"target":"synthetic"}', encoding="utf-8")
            sha_at_read = hashlib.sha256(cfg.read_bytes()).hexdigest()
            values_at_read = json.loads(cfg.read_text(encoding="utf-8"))
            # A long run may overlap with a user edit. Provenance must retain
            # the ORIGINAL observed bytes and values, never a later file hash.
            cfg.write_text('{"target":"edited while running"}', encoding="utf-8")
            plan = build_plan(**BASE).as_dict()
            summary = {
                "samples": 568, "last_sample_time_s": 5670,
                "access_samples": 46, "windows": [],
                "max_elevation_deg": 86.3, "minimum_slant_range_km": 500.9,
                "checks_passed": True, "payload": None,
            }
            write_run_explanation(
                output=root / "output",
                plan=plan,
                configs={"ground": (cfg, values_at_read, sha_at_read)},
                summary=summary,
                software={"bsk": "2.12.2"},
                notes=["not real satellite"],
            )
            saved = json.loads((root / "output" / "run_manifest.json").read_text())
            self.assertEqual(saved["runtime"]["horizon_s"], BASE["orbit_period_s"])
            self.assertEqual(saved["inputs"]["ground"]["values"]["target"], "synthetic")
            self.assertEqual(saved["inputs"]["ground"]["sha256"], sha_at_read)
            self.assertNotEqual(saved["inputs"]["ground"]["sha256"], hashlib.sha256(cfg.read_bytes()).hexdigest())
            self.assertIn("not real satellite", saved["limitations"])
            report = (root / "output" / "RESULTS_EXPLAINED.md").read_text()
            self.assertIn("НЕ", report)
            self.assertIn("5670", report)


if __name__ == "__main__":
    unittest.main()
