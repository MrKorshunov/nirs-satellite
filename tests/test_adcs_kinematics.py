"""Independent attitude geometry tests; no Basilisk/numpy required."""
import math
import unittest

from experiments.adcs_01.kinematics import (
    mrp_dcm_BN, true_boresight_error_deg, dcm_orthogonality_error,
)


class ADCSKinematicsTests(unittest.TestCase):
    def test_identity_body_to_inertial(self):
        C = mrp_dcm_BN([0, 0, 0])
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(C[i][j], float(i==j), places=14)
        self.assertAlmostEqual(
            true_boresight_error_deg([0,0,0], [0,0,0], [0,0,100],
                                     [0,0,1]), 0, places=10)

    def test_known_quarter_turn_is_physically_correct(self):
        # Spacecraft body x-axis rotated +90 degrees relative to inertial x,
        # so body boresight +x points toward inertial +y.
        s = [0, 0, math.tan(math.pi / 8)]
        C = mrp_dcm_BN(s)
        self.assertAlmostEqual(C[0][0], 0.0, places=13)
        self.assertAlmostEqual(C[0][1], 1.0, places=13)
        self.assertAlmostEqual(C[1][0], -1.0, places=13)
        self.assertAlmostEqual(
            true_boresight_error_deg(s, [0,0,0], [0,10,0], [1,0,0]),
            0, places=10)
        self.assertAlmostEqual(
            true_boresight_error_deg(s, [0,0,0], [10,0,0], [1,0,0]),
            90, places=10)
        self.assertLess(dcm_orthogonality_error(s), 1e-13)

    def test_antipodal_los(self):
        self.assertAlmostEqual(
            true_boresight_error_deg([0,0,0], [0,0,0], [0,0,-100],
                                     [0,0,1]), 180, places=12)

    def test_orthogonality_for_mixed_rotation(self):
        for sigma in ([0.1,-0.2,0.3], [-0.31,0.17,0.22], [0.7,-0.5,0.4]):
            self.assertLess(dcm_orthogonality_error(sigma), 1e-13)

    def test_invalid_geometry_rejected(self):
        with self.assertRaises(ValueError):
            true_boresight_error_deg([0,0,0], [1,2,3], [1,2,3], [0,0,1])
        with self.assertRaises(ValueError):
            true_boresight_error_deg([0,0,0], [0,0,0], [0,0,1], [0,0,10])
        with self.assertRaises(ValueError):
            mrp_dcm_BN([0, float("nan"), 0])


if __name__ == "__main__":
    unittest.main()
