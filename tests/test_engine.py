import unittest
from archive.v01.model import Scenario, Task, Contact
from archive.v01.engine import simulate


def task(name, start=0, end=10, size=100, deadline=1000, priority=1):
    return Task(name, start, end, size, deadline, priority)


def contact(start=20, end=100, rate=10):
    return Contact(start, end, rate)


class TestInformationFlow(unittest.TestCase):
    def test_single_delivery(self):
        out = simulate(Scenario(100, (task("a"),), (contact(),)))
        self.assertEqual(out.completed_on_time, {"a"})
        self.assertEqual(out.delivered_bytes, 100)
        self.assertEqual(out.weighted_completion, 1)

    def test_deadline_exact_inclusive(self):
        out = simulate(Scenario(100, (task("a", deadline=30),), (contact(20, 30),)))
        self.assertEqual(out.completed_on_time, {"a"})

    def test_late_delivery_not_success(self):
        out = simulate(Scenario(100, (task("a", deadline=25),), (contact(20, 40),)))
        self.assertEqual(out.delivered_late, {"a"})
        self.assertEqual(out.weighted_completion, 0)

    def test_capture_memory_overflow(self):
        tasks = (task("a", 0, 5, 80), task("b", 6, 10, 30))
        out = simulate(Scenario(100, tasks, (contact(),)))
        self.assertEqual(out.rejected_memory, {"b"})
        self.assertEqual(out.max_memory_bytes, 80)

    def test_two_separate_contacts_finish_one_product(self):
        cs = (contact(20, 25, 10), contact(40, 45, 10))
        out = simulate(Scenario(100, (task("a"),), cs))
        self.assertEqual(out.completed_on_time, {"a"})
        self.assertEqual(out.delivered_bytes, 100)
        self.assertEqual(len([x for x in out.events if x['type'] == 'downlink']), 2)

    def test_partial_delivery_retains_full_storage(self):
        tasks = (task("a", 0, 10, 100), task("b", 30, 40, 10))
        cs = (contact(20, 25, 10),)
        out = simulate(Scenario(100, tasks, cs))
        self.assertIn("a", out.undelivered)
        self.assertIn("b", out.rejected_memory)

    def test_capture_blocks_radio_transmission(self):
        tasks = (task("a", 0, 10, 100), task("b", 20, 30, 10))
        cs = (contact(15, 40, 10),)
        out = simulate(Scenario(120, tasks, cs))
        self.assertEqual(out.completed_on_time, {"a", "b"})
        intervals = [(e['time_s'], e['end_s']) for e in out.events if e['type'] == 'downlink']
        self.assertTrue(all(not (a < 30 and b > 20) for a, b in intervals))

    def test_fifo_vs_edf(self):
        tasks = (task("a", 0, 5, 90, 120), task("b", 6, 10, 90, 60))
        cs = (contact(20, 29, 10), contact(80, 89, 10))
        case = Scenario(180, tasks, cs)
        self.assertEqual(simulate(case, "fifo").completed_on_time, {"a"})
        self.assertEqual(simulate(case, "edf").completed_on_time, {"a", "b"})

    def test_invalid_overlap_captures(self):
        case = Scenario(100, (task("a", 0, 10), task("b", 9, 20)), ())
        with self.assertRaises(ValueError):
            simulate(case)

    def test_invalid_overlap_contacts(self):
        case = Scenario(100, (task("a"),), (contact(20, 30), contact(29, 40)))
        with self.assertRaises(ValueError):
            simulate(case)

    def test_valid_no_tasks(self):
        out = simulate(Scenario(100, (), ()))
        self.assertEqual(out.weighted_completion, 0.0)
        self.assertEqual(out.task_count, 0)

    def test_no_contact_no_delivery(self):
        out = simulate(Scenario(100, (task("a"),), ()))
        self.assertEqual(out.undelivered, {"a"})
        self.assertEqual(out.weighted_completion, 0)

    def test_no_transmission_before_capture(self):
        out = simulate(Scenario(100, (task("a", 20, 30),),
                                (contact(0, 10), contact(40, 50))))
        self.assertEqual(out.completed_on_time, {"a"})
        segments = [x for x in out.events if x["type"] == "downlink"]
        self.assertTrue(all(x["time_s"] >= 30 for x in segments))

    def test_weighted_score(self):
        tasks = (task("a", 0, 5, 100, 50, 3), task("b", 6, 10, 100, 50, 1))
        out = simulate(Scenario(200, tasks, (contact(20, 30, 10),)))
        self.assertEqual(out.weighted_completion, 0.75)


if __name__ == '__main__':
    unittest.main()
