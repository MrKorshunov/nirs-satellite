"""Pure geometry and external-plan validation for physical nadir swaths."""
import copy,json,math,unittest
from nirs_satellite.input_paths import input_path
from experiments.mission_03.universal_inputs import validate_program
from experiments.mission_03.swath_geometry import (
    ground_point_from_position,polygon_distance_m,
    swath_intersects_region,nadir_footprint_width_m,great_circle_distance_m,
)

class UniversalExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=json.loads(input_path("mission_mixed_demo").read_text())
        cls.reg=json.loads(input_path("territories").read_text())
        cls.hw=json.loads(input_path("camera_storage_radio").read_text())
        cls.power=json.loads(input_path("power").read_text())

    def validate(self,cfg):
        return validate_program(cfg,self.reg,self.hw,self.power,0.5)

    def test_mixed_point_and_strip(self):
        self.assertEqual(len(self.validate(self.cfg)),2)
        self.assertEqual([x.get("kind","point") for x in self.cfg["tasks"]],
                         ["point","point","strip"])

    def test_one_target_program_is_valid(self):
        c=copy.deepcopy(self.cfg);c["tasks"]=c["tasks"][:1]
        self.validate(c)

    def test_many_targets_program_is_valid(self):
        c=copy.deepcopy(self.cfg);c["tasks"]=c["tasks"][:1]*12
        for n,job in enumerate(c["tasks"]):
            job["id"]=f"SHOT_{n:02d}"
        self.validate(c)

    def test_duplicate_ids_forbidden(self):
        c=copy.deepcopy(self.cfg);c["tasks"][1]["id"]=c["tasks"][0]["id"]
        with self.assertRaises(ValueError):self.validate(c)

    def test_wrong_region_rejected(self):
        c=copy.deepcopy(self.cfg);c["tasks"][2]["region_id"]="MISSING"
        with self.assertRaises(ValueError):self.validate(c)

    def test_no_algorithm_choices(self):
        c=copy.deepcopy(self.cfg);c["execution_policy"]="priority"
        with self.assertRaises(ValueError):self.validate(c)

    def test_nadir_groundpoint_identity(self):
        lat,lon,h=ground_point_from_position((6878137,0,0),
             [[1,0,0],[0,1,0],[0,0,1]],6378137)
        self.assertAlmostEqual(lat,0)
        self.assertAlmostEqual(lon,0)
        self.assertAlmostEqual(h,500000)

    def test_swath_overlap_region(self):
        polygon=self.reg["regions"][0]["polygon_lat_lon_deg"]
        ok,dist,width=swath_intersects_region(20,50,500000,15,polygon,6378137)
        self.assertTrue(ok)
        self.assertLess(dist,0)
        self.assertGreater(width,100000)
        ok,_,_=swath_intersects_region(0,0,500000,15,polygon,6378137)
        self.assertFalse(ok)

    def test_great_circle_length(self):
        self.assertAlmostEqual(great_circle_distance_m((0,0),(0,1),6378137),
                               math.pi*6378137/180,places=4)

    def test_invalid_fov(self):
        with self.assertRaises(ValueError):
            nadir_footprint_width_m(500000,90)

if __name__=="__main__": unittest.main()
