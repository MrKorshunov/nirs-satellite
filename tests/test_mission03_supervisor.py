"""Mission03 pure-Python guards: explicit event evidence and energy reserve."""
import copy
import json
import unittest
from nirs_satellite.input_paths import input_path
from experiments.mission_03.parameters import validate
from experiments.mission_03.supervisor import Supervisor


class Mission03Tests(unittest.TestCase):
    def setUp(self):
        self.multi=json.loads(input_path("multitarget_demo").read_text(encoding="utf-8"))
        self.hardware={
            "mission":json.loads(input_path("camera_storage_radio").read_text(encoding="utf-8")),
            "power":json.loads(input_path("power").read_text(encoding="utf-8")),
        }

    def test_realistic_two_targets_validate(self):
        validate(self.multi,self.hardware,0.5)

    def test_reject_duplicate_partition(self):
        cfg=copy.deepcopy(self.multi)
        cfg["targets"][1]["id"]=cfg["targets"][0]["id"]
        with self.assertRaises(ValueError):
            validate(cfg,self.hardware,0.5)

    def test_reject_overfilled_storage(self):
        cfg=copy.deepcopy(self.multi)
        cfg["targets"][1]["product_bytes"]=5000000
        with self.assertRaises(ValueError):
            validate(cfg,self.hardware,0.5)

    def test_reject_impossible_command_interval(self):
        cfg=copy.deepcopy(self.multi)
        cfg["command_interval_s"]=0.3
        with self.assertRaises(ValueError):
            validate(cfg,self.hardware,0.5)

    def test_switch_requires_real_capture_signal(self):
        sv=Supervisor(("A","B"),5)
        switch,power=sv.update(5,0,40)
        self.assertFalse(switch)
        self.assertTrue(power)
        switch,power=sv.update(10,1,39)
        self.assertTrue(switch)
        self.assertEqual(sv.active_index,1)
        self.assertEqual(sv.events[0]["target_id"],"A")
        switch,power=sv.update(15,1,38)
        self.assertFalse(switch)
        switch,power=sv.update(20,2,37)
        self.assertFalse(switch)
        self.assertTrue(sv.finished_capturing)

    def test_energy_safe_mode_and_recovery(self):
        sv=Supervisor(("A","B"),5)
        _,ok=sv.update(5,0,4.9)
        self.assertFalse(ok)
        _,ok=sv.update(10,0,5.1)
        self.assertTrue(ok)
        self.assertEqual([x["event"] for x in sv.events],
                         ["power_safe_on","power_safe_off"])

    def test_no_extra_capture_from_rearmed_controller(self):
        sv=Supervisor(("A","B"),5)
        with self.assertRaises(AssertionError):
            sv.update(5,3,60)


if __name__=="__main__":
    unittest.main()
