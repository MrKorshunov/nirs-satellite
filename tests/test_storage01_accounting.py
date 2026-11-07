"""Pure Python storage capacity and bit accounting tests."""
import unittest

from experiments.storage_01.accounting import verify_storage


class StorageAccountingTests(unittest.TestCase):
    def test_conserve_single_image(self):
        r=verify_storage(
            [0, .5, 1, 1.5], [0, 0, 8_000_000, 8_000_000],
            80_000_000, [{"product_bits":8_000_000}],
        )
        self.assertEqual(r["final_storage_bits"],8_000_000)
        self.assertEqual(r["delivered_bits"],0)
        self.assertTrue(r["integrity_passed"])

    def test_over_capacity(self):
        with self.assertRaisesRegex(AssertionError,"capacity"):
            verify_storage([0,.5,1],[0,10,20], 15, [{"product_bits":20}])

    def test_dropped_bits(self):
        with self.assertRaisesRegex(AssertionError,"balance mismatch"):
            verify_storage([0,.5,1],[0,100,200],1000,[{"product_bits":300}])

    def test_unexpected_data_removal(self):
        with self.assertRaisesRegex(AssertionError,"decreased"):
            verify_storage([0,.5,1],[0,500,400],1000,[{"product_bits":400}])

    def test_nonfinite(self):
        with self.assertRaises(ValueError):
            verify_storage([0,.5,1],[0,float("nan"),0],1000,[])


if __name__=="__main__":
    unittest.main()
