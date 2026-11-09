"""Independent, standard-library-only checks: run with the existing unit tests."""
import math
import unittest

from nirs_satellite.orbit.analytical import (
    circular_speed_m_s,
    orbital_period_s,
    relative_span,
)


class TwoBodyAnalyticalTests(unittest.TestCase):
    MU = 3.986004418e14
    RADIUS_M = 6378137.0 + 500000.0

    def test_reference_period(self):
        self.assertAlmostEqual(orbital_period_s(self.RADIUS_M, self.MU) / 60,
                               94.6163004754, places=5)

    def test_reference_speed(self):
        self.assertAlmostEqual(circular_speed_m_s(self.RADIUS_M, self.MU) / 1000,
                               7.61260817322, places=6)

    def test_scaling_kepler_third_law(self):
        p1 = orbital_period_s(self.RADIUS_M, self.MU)
        p2 = orbital_period_s(2 * self.RADIUS_M, self.MU)
        self.assertAlmostEqual(p2 / p1, math.sqrt(8), places=12)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            orbital_period_s(-1, self.MU)
        with self.assertRaises(ValueError):
            circular_speed_m_s(1, 0)

    def test_relative_span(self):
        self.assertAlmostEqual(relative_span([10, 10.1, 9.9]), .02)
        with self.assertRaises(ValueError):
            relative_span([])


if __name__ == "__main__":
    unittest.main()
