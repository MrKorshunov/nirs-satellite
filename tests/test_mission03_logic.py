"""Independent Mission03 acceptance input and power-policy tests."""
import copy
import unittest
from experiments.mission_03.logic import validate, permitted, stage_for_sample

def fixture():
    return {
        "scenario_id":"mission3",
        "provenance":"SYNTHETIC test",
        "control_step_s":5.0,"reserve_wh":5.0,
        "reserve_guard_wh":0.15,"battery_reenable_hysteresis_wh":0.5,
        "tasks":[
            {"id":"A","lat_deg":14,"lon_deg":43,"altitude_m":0,"minimum_elevation_deg":10,
             "maximum_range_m":-1,"deadline_s":720},
            {"id":"B","lat_deg":14.7,"lon_deg":43.35,"altitude_m":0,"minimum_elevation_deg":10,
             "maximum_range_m":-1,"deadline_s":720}
        ]
    }

class Tests(unittest.TestCase):
    def check(self, cfg):
        return validate(cfg,step_s=0.5,product_name="A",partition_name="A",
                        product_bytes=1000000,storage_bytes=4000000,initial_energy_wh=65)

    def test_valid(self):
        self.check(fixture())

    def test_two_distinct_targets(self):
        cfg=fixture()
        cfg["tasks"][1]["lon_deg"]=cfg["tasks"][0]["lon_deg"]
        cfg["tasks"][1]["lat_deg"]=cfg["tasks"][0]["lat_deg"]
        with self.assertRaises(ValueError):self.check(cfg)

    def test_partition_consistency(self):
        cfg=fixture()
        cfg["tasks"][0]["id"]="C"
        with self.assertRaises(ValueError):self.check(cfg)

    def test_memory_capacity(self):
        cfg=fixture()
        with self.assertRaises(ValueError):
            validate(cfg,step_s=0.5,product_name="A",partition_name="A",
                     product_bytes=1000000,storage_bytes=1000000,initial_energy_wh=65)

    def test_cadence_must_divide_step(self):
        cfg=fixture()
        cfg["control_step_s"]=5.3
        with self.assertRaises(ValueError):self.check(cfg)

    def test_provenance_required(self):
        cfg=fixture()
        cfg["provenance"]="actual flight vehicle"
        with self.assertRaises(ValueError):self.check(cfg)

    def test_hysteresis(self):
        kwargs=dict(reserve_wh=5,guard_wh=.15,hysteresis_wh=.5)
        self.assertTrue(permitted(65,previously_permitted=True,**kwargs))
        self.assertFalse(permitted(5.14,previously_permitted=True,**kwargs))
        self.assertFalse(permitted(5.4,previously_permitted=False,**kwargs))
        self.assertTrue(permitted(5.65,previously_permitted=False,**kwargs))

    def test_boundary_sample_belongs_to_first_target(self):
        self.assertEqual(stage_for_sample(85.0,85.0,.5),0)
        self.assertEqual(stage_for_sample(85.5,85.0,.5),1)
        self.assertEqual(stage_for_sample(80.0,None,.5),0)

if __name__=="__main__":
    unittest.main()
