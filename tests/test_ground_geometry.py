"""Ground 01: independent checks without Basilisk dependencies."""
import math
import unittest

from experiments.ground_01.geometry import (
    norm3, rotate_z, elevation_from_inertial, access_windows
)


class GroundGeometryTest(unittest.TestCase):
    def test_overhead(self):
        r=6378137.0
        self.assertAlmostEqual(elevation_from_inertial((r+500000.0,0,0),(r,0,0)),
                               math.pi/2,places=10)

    def test_below_horizon(self):
        r=6378137.0
        angle=math.radians(75)
        spacecraft=((r+500000)*math.cos(angle),
                    (r+500000)*math.sin(angle),0)
        self.assertLess(elevation_from_inertial(spacecraft,(r,0,0)),0)

    def test_earth_rotation(self):
        a=rotate_z((1,0,2),math.pi/2)
        self.assertAlmostEqual(a[0],0,places=10)
        self.assertAlmostEqual(a[1],1,places=10)
        self.assertEqual(a[2],2)
        self.assertAlmostEqual(norm3(a),math.sqrt(5),places=10)

    def test_one_unclipped_window(self):
        windows=access_windows([0,10,20,30,40],[False,True,True,False,False])
        self.assertEqual(len(windows),1)
        self.assertEqual(windows[0]["first_access_sample_s"],10)
        self.assertEqual(windows[0]["first_inaccessible_sample_s"],30)
        self.assertFalse(windows[0]["window_start_clipped"])

    def test_clipped_window(self):
        windows=access_windows([0,10,20],[True,True,True])
        self.assertTrue(windows[0]["window_start_clipped"])
        self.assertTrue(windows[0]["window_end_clipped"])

    def test_invalid_times(self):
        with self.assertRaises(ValueError):
            access_windows([0,0],[False,True])


if __name__ == "__main__":
    unittest.main()
