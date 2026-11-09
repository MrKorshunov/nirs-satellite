"""Mission synthetic input checks run with plain Python before Basilisk install."""
import copy
import json
from pathlib import Path
import unittest

from nirs_satellite.input_paths import input_path

from experiments.mission_01.parameters import validate_config

BASE = input_path("camera_storage_radio")


class MissionInputTests(unittest.TestCase):
    def setUp(self):
        self.params = json.loads(BASE.read_text(encoding="utf-8"))

    def test_default_valid(self):
        validate_config(self.params, 0.5)

    def test_missing_provenance(self):
        p = copy.deepcopy(self.params)
        p["provenance"] = "REAL SPACECRAFT"
        with self.assertRaises(ValueError):
            validate_config(p, 0.5)

    def test_invalid_capacity(self):
        p = copy.deepcopy(self.params)
        p["storage"]["capacity_bytes"] = 100_000
        with self.assertRaises(ValueError):
            validate_config(p, 0.5)

    def test_negative_radio_rate(self):
        p = copy.deepcopy(self.params)
        p["downlink"]["rate_bits_per_s"] = -1
        with self.assertRaises(ValueError):
            validate_config(p, 0.5)

    def test_step_must_match_instantaneous_synthetic_exposure(self):
        with self.assertRaises(ValueError):
            validate_config(self.params, 1.0)

    def test_incompatible_product_partition(self):
        p = copy.deepcopy(self.params)
        p["storage"]["partition_name"] = "unassigned"
        with self.assertRaises(ValueError):
            validate_config(p, 0.5)

    def test_packet_cannot_exceed_or_not_divide_product(self):
        for packet_bytes in (1_000_001, 300_000):
            p = copy.deepcopy(self.params)
            p["downlink"]["packet_bytes"] = packet_bytes
            with self.subTest(packet_bytes=packet_bytes), self.assertRaises(ValueError):
                validate_config(p, 0.5)

    def test_invalid_ground_station_geometry(self):
        p = copy.deepcopy(self.params)
        p["downlink"]["ground_station"]["latitude_deg"] = 102
        with self.assertRaises(ValueError):
            validate_config(p, 0.5)


if __name__ == "__main__":
    unittest.main()
