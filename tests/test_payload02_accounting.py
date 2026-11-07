"""Independent checks for physical attitude-gated instrument events."""
import unittest

from experiments.payload_02.accounting import verify_capture


def data(**overrides):
    kwargs=dict(
        times_s=[0.0, 0.5, 1.0], has_access=[False, True, True],
        commands=[0, 1, 0], rates=[0.0, 16_000_000.0, 0.0],
        boresight_errors_deg=[40.0, 1.0, 2.0],
        guidance_mrp_norms=[0.2, 0.004, 0.005],
        rate_errors_rad_s=[0.1, 0.001, 0.002],
        step_s=0.5, bytes_per_product=1_000_000,
        max_boresight_error_deg=5.0, max_rate_error_rad_s=0.01,
        mrp_tolerance=0.02182,
    )
    kwargs.update(overrides)
    return kwargs


class Payload02AccountingTests(unittest.TestCase):
    def test_one_product_with_physical_pointing(self):
        events=verify_capture(**data())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["product_bits"], 8_000_000)
        self.assertFalse(events[0]["ideal_pointing"])
        self.assertTrue(events[0]["physical_adcs_guidance_used"])
        self.assertEqual(events[0]["actual_boresight_error_deg"],1.0)

    def test_reject_bad_actual_boresight_even_when_guidance_small(self):
        with self.assertRaisesRegex(AssertionError,"physical boresight"):
            verify_capture(**data(boresight_errors_deg=[40,7,2]))

    def test_reject_bad_guidance_mrp(self):
        with self.assertRaisesRegex(AssertionError,"MRP"):
            verify_capture(**data(guidance_mrp_norms=[0.2,0.04,0.005]))

    def test_reject_rate_error(self):
        with self.assertRaisesRegex(AssertionError,"rate"):
            verify_capture(**data(rate_errors_rad_s=[0.1,0.02,0.002]))

    def test_reject_capture_outside_access(self):
        with self.assertRaisesRegex(AssertionError,"visibility window"):
            verify_capture(**data(has_access=[False,False,True]))

    def test_reject_falsely_reported_data(self):
        with self.assertRaisesRegex(AssertionError,"Command and actual"):
            verify_capture(**data(rates=[0,0,0]))

    def test_reject_unsynchronized_values(self):
        with self.assertRaises(ValueError):
            verify_capture(**data(boresight_errors_deg=[0,1]))

    def test_reject_nan(self):
        with self.assertRaises(ValueError):
            verify_capture(**data(boresight_errors_deg=[0,float("nan"),0]))


if __name__ == "__main__":
    unittest.main()
