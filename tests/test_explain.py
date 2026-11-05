"""Check that the transparency report is derived from the scenario."""
import tempfile
from pathlib import Path
import unittest
from explain import report


class ReportTests(unittest.TestCase):
    def test_report_contains_input_and_both_policies(self):
        source = Path(__file__).resolve().parent.parent / "scenarios" / "demo.json"
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "report.html"
            report(source, destination)
            body = destination.read_text(encoding="utf-8")
        self.assertIn("scenarios/demo.json", body.replace("\\", "/"))
        self.assertIn("180.00 МБ", body)
        self.assertIn("A_fields", body)
        self.assertIn("B_water", body)
        self.assertIn("FIFO — K = 0.333", body)
        self.assertIn("EDF — K = 0.667", body)
        self.assertIn("синтетический контрольный сценарий", body)


if __name__ == "__main__":
    unittest.main()
