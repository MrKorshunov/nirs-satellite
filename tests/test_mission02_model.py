"""Standard-library tests of Mission 02 operations and conservation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from experiments.mission_02.model import (
    State, simulate, validate, off_nadir_deg, ground_vector,
    in_parallel_shadow, rate_from_friis,
)

BASE = Path(__file__).resolve().parents[1] / "experiments" / "mission_02" / "config.json"


def fixture():
    config = json.loads(BASE.read_text(encoding="utf-8"))
    config["earth"]["rotation_rate_rad_s"] = 0
    config["tasks"] = [{
        "id": "A", "lat_deg": 0, "lon_deg": 0, "release_s": 0,
        "deadline_s": 500, "priority": 2, "product_bytes": 10000,
        "exposure_s": 10, "min_elevation_deg": 10,
    }]
    config["stations"] = [{
        "id": "GS", "lat_deg": 0, "lon_deg": 0, "min_elevation_deg": 10,
    }]
    radius = config["earth"]["radius_m"]
    states = [State(i*10.0, (radius+500000, 0.0, 0.0)) for i in range(60)]
    return config, states


class Mission02ModelTests(unittest.TestCase):
    def test_valid_config(self):
        cfg, states = fixture()
        validate(cfg, states[1].t_s-states[0].t_s)

    def test_capture_downlink_and_balance(self):
        cfg, states = fixture()
        out = simulate(states, cfg, "edf")
        self.assertEqual(out["summary"]["captured"], 1)
        self.assertEqual(out["summary"]["fully_delivered"], 1)
        self.assertEqual(out["summary"]["weighted_on_time_fraction"], 1)
        self.assertEqual(out["summary"]["balance_error_bits"], 0)
        self.assertTrue(all(r["storage_bits"] >= 0 for r in out["trace"]))

    def test_no_station_access_keeps_data(self):
        cfg, states = fixture()
        cfg["stations"][0]["lon_deg"] = 180
        summary = simulate(states, cfg, "fifo")["summary"]
        self.assertEqual(summary["captured"], 1)
        self.assertEqual(summary["fully_delivered"], 0)
        self.assertEqual(summary["stored_bits"], summary["generated_bits"])

    def test_storage_rejects_product(self):
        cfg, states = fixture()
        cfg["spacecraft"]["storage_capacity_bytes"] = 5000
        summary = simulate(states, cfg, "edf")["summary"]
        self.assertEqual(summary["captured"], 0)
        self.assertEqual(summary["generated_bits"], 0)

    def test_slow_link_cannot_transmit_full_packets(self):
        cfg, states = fixture()
        cfg["radio"]["nominal_rate_bps"] = 1
        summary = simulate(states, cfg, "priority")["summary"]
        self.assertEqual(summary["captured"], 1)
        self.assertEqual(summary["transmitted_bits"], 0)

    def test_packet_credit_accumulates_between_samples(self):
        cfg, states = fixture()
        cfg["radio"]["nominal_rate_bps"] = 1000
        # 10 s * 1000 bit/s is below the 40000-bit packet size.
        # Several consecutive contact samples must still complete a packet.
        summary = simulate(states, cfg, "edf")["summary"]
        self.assertEqual(summary["captured"], 1)
        self.assertEqual(summary["transmitted_bits"], 80000)
        self.assertEqual(summary["balance_error_bits"], 0)

    def test_low_battery_prevents_capture(self):
        cfg, states = fixture()
        cfg["power"]["initial_wh"] = 5.01
        cfg["power"]["solar_charge_w"] = 1e-8
        cfg["power"]["sun_direction_inertial"] = [-1, 0, 0]
        summary = simulate(states, cfg, "edf")["summary"]
        self.assertEqual(summary["captured"], 0)
        self.assertGreaterEqual(summary["min_battery_wh"], cfg["power"]["reserve_wh"])

    def test_spherical_geometry_and_eclipse(self):
        cfg, states = fixture()
        earth = cfg["earth"]["radius_m"]
        target = ground_vector(0, 0, earth, 0, 0)
        self.assertAlmostEqual(off_nadir_deg(states[0].pos_m, target), 0, places=7)
        self.assertFalse(in_parallel_shadow(states[0].pos_m, earth, [1, 0, 0]))
        self.assertTrue(in_parallel_shadow((-earth-500000, 0, 0), earth, [1, 0, 0]))

    def test_friis_rate_decreases_with_range(self):
        cfg, _ = fixture()
        radio = cfg["radio"]
        self.assertGreater(rate_from_friis(1000000, radio),
                           rate_from_friis(10000000, radio))
        self.assertLessEqual(rate_from_friis(1000000, radio),
                             radio["nominal_rate_bps"])

    def test_policy_validation(self):
        cfg, states = fixture()
        with self.assertRaises(ValueError):
            simulate(states, cfg, "unverified")

    def test_invalid_duplicate_ids(self):
        cfg, _ = fixture()
        cfg["tasks"].append(copy.deepcopy(cfg["tasks"][0]))
        with self.assertRaises(ValueError):
            validate(cfg, 10)


if __name__ == "__main__":
    unittest.main()
