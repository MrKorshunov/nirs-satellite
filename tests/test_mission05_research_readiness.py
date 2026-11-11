"""Mission05: dated geodesy, timed external schedules and union coverage.

All pure-Python tests deliberately run before installing Basilisk, ensuring
the scientific inputs, units and reporting math can be inspected independently.
"""
from __future__ import annotations
import copy,json,math,unittest
from datetime import datetime,timezone
from experiments.mission_03.geo_time import (
    WGS84_A,parse_utc,gmst_degrees,ecef_to_geodetic,geodetic_to_ecef,
    geocentric_latitude_for_geodetic,utc_at_elapsed,epoch_parameters)
from experiments.mission_03.coverage import compute_coverage
from experiments.mission_03.universal_inputs import validate_program
from nirs_satellite.input_paths import input_path

class GeodesyAndTimedSchedule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=json.loads(input_path("mission_mixed_demo").read_text())
        cls.reg=json.loads(input_path("territories").read_text())
        cls.hw=json.loads(input_path("camera_storage_radio").read_text())
        cls.power=json.loads(input_path("power").read_text())

    def validate(self,c):
        return validate_program(c,self.reg,self.hw,self.power,0.5)

    def test_real_utc_requires_explicit_z(self):
        d=parse_utc("2026-11-11T00:00:00Z")
        self.assertEqual(d.utcoffset().total_seconds(),0)
        for bad in ("2026-11-11T00:00:00","2026-11-11T00:00:00+02:00","bad"):
            with self.assertRaises(ValueError):parse_utc(bad)

    def test_reference_gmst_j2000(self):
        dt=datetime(2000,1,1,12,tzinfo=timezone.utc)
        self.assertAlmostEqual(gmst_degrees(dt),280.46,delta=0.03)

    def test_gmst_one_sidereal_day(self):
        a=gmst_degrees(parse_utc("2026-11-11T00:00:00Z"))
        b=gmst_degrees(parse_utc("2026-11-12T00:00:00Z"))
        self.assertAlmostEqual((b-a)%360.,0.9856,delta=0.002)

    def test_wgs84_ellipsoid_roundtrip(self):
        for lat,lon,h in ((0,0,0),(45,25,500000),(-32,70,3000)):
            with self.subTest(lat=lat):
                ecef=geodetic_to_ecef(lat,lon,h)
                lat2,lon2,h2=ecef_to_geodetic(ecef)
                self.assertAlmostEqual(lat,lat2,places=8)
                self.assertAlmostEqual(lon,lon2,places=8)
                self.assertAlmostEqual(h,h2,places=3)

    def test_geodetic_vs_geocentric_latitude(self):
        self.assertLess(geocentric_latitude_for_geodetic(45),45)

    def test_iso_time_elapsed(self):
        self.assertEqual(utc_at_elapsed("2026-11-11T00:00:00Z",90),
                         "2026-11-11T00:01:30Z")

    def test_dated_mode_is_explicit(self):
        c=json.loads(input_path("time_reference_utc_demo").read_text())
        ref=epoch_parameters(c)
        self.assertEqual(ref["mode"],"utc_approx_wgs84")
        self.assertIn("gmst_at_epoch_deg",ref)

    def test_valid_timed_schedule(self):
        c=json.loads(input_path("scheduled_program_example").read_text())
        self.validate(c)

    def test_invalid_timed_windows(self):
        for start,end in ((90,85),(91.2,150),(-1,100),(90,800)):
            c=json.loads(input_path("scheduled_program_example").read_text())
            c["tasks"][1]["planned_start_s"]=start
            c["tasks"][1]["planned_end_s"]=end
            with self.subTest(start=start,end=end),self.assertRaises(ValueError):
                self.validate(c)

    def test_coverage_union_does_not_double_count(self):
        region={"id":"R","polygon_lat_lon_deg":[[0,0],[0,0.1],[0.1,0.1],[0.1,0]]}
        line={"task_region_id":"R","task":"S","lat_deg":0.055,"lon_deg":0.05,
              "previous_lat_deg":0.045,"previous_lon_deg":0.05,
              "swath_width_m":10000.}
        first=compute_coverage({"R":region},[line],coarse_cells=4000,fine_cells=9000)["R"]
        double=compute_coverage({"R":region},[line,line],coarse_cells=4000,fine_cells=9000)["R"]
        self.assertEqual(first["covered_cells"],double["covered_cells"])
        self.assertGreater(first["covered_area_m2"],0)
        self.assertLess(first["coverage_percent"],100)

    def test_no_physical_lines_means_zero_coverage(self):
        region={"id":"R","polygon_lat_lon_deg":[[0,0],[0,0.01],[0.01,0.01],[0.01,0]]}
        got=compute_coverage({"R":region},[],coarse_cells=2000,fine_cells=4000)["R"]
        self.assertEqual(got["coverage_percent"],0)
        self.assertGreater(got["region_area_m2"],0)

if __name__=="__main__":
    unittest.main()
