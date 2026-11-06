"""Tests that do not require Basilisk."""
import unittest

from experiments.payload_01.accounting import validate_generation


class PayloadAccountingTests(unittest.TestCase):
    def test_one_access_event(self):
        events = validate_generation(
            [0, 10, 20, 30],
            [False, True, True, False],
            [0, 1, 0, 0],
            [0, 800_000, 0, 0],
            10, 8_000_000,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["start_time_s"], 10)
        self.assertEqual(events[0]["end_time_s"], 20)
        self.assertEqual(events[0]["product_bytes"], 1_000_000)

    def test_no_access_fails_capture_requirement(self):
        with self.assertRaisesRegex(AssertionError, "Expected exactly one product"):
            validate_generation([0,10,20], [False]*3, [0]*3,
                                [0.0]*3, 10, 8_000_000)

    def test_outside_access_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "outside the visibility"):
            validate_generation([0,10,20], [False]*3, [0,1,0],
                                [0,800_000,0], 10, 8_000_000)

    def test_missing_data_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "rate disagree"):
            validate_generation([0,10,20], [False,True,False],
                                [0,1,0], [0,0,0], 10, 8_000_000)

    def test_wrong_volume_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Unexpected volume"):
            validate_generation([0,10,20], [False,True,False],
                                [0,1,0], [0,400_000,0], 10, 8_000_000)

    def test_duplicate_command_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Expected exactly one product"):
            validate_generation([0,10,20,30], [False,True,True,False],
                                [0,1,1,0], [0,800_000,800_000,0],
                                10,8_000_000)

    def test_invalid_steps(self):
        with self.assertRaises(ValueError):
            validate_generation([0,10],[True,True],[0,1],[0,800_000],0,8_000_000)


if __name__ == "__main__":
    unittest.main()
