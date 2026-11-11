"""Mission05 regression: schedule arithmetic, UTC/UT1 sidereal epoch, WGS84 sampled swath union."""
from __future__ import annotations
import copy, importlib.util, math, unittest

from experiments.mission_03.epoch import read_epoch, gmst_deg, date_at, epoch_metadata
from experiments.mission_03.timeline import (
    validate_windows,task_window,within_task_window,radio_window_open,schedule_task_record
)
from experiments.mission_03.swath_geometry import wgs84_subpoint_from_position

class TimeAndScheduleTests(unittest.TestCase):
    def setUp(self):
        self.jobs=[{"id":"A","kind":"point","release_s":0,"deadline_s":200,
                    "planned_start_s":50,"planned_end_s":120}]
        self.cfg={"tasks":self.jobs,"downlink_windows":[
            {"start_s":10,"end_s":25},{"start_s":80,"end_s":100}]}

    def test_j2000_gmst_reference(self):
        self.assertAlmostEqual(gmst_deg("2000-01-01T12:00:00Z"),280.46061837,places=5)

    def test_explicit_real_utc_epoch_resolves_sidereal_angle(self):
        self.assertLess(min(gmst_deg("2026-11-11T20:35:59.964Z"),
                            360-gmst_deg("2026-11-11T20:35:59.964Z")),0.02)

    def test_ut1_dut1_changes_orientation(self):
        self.assertAlmostEqual(
            (gmst_deg("2026-11-11T00:00:00Z",0.2)-
             gmst_deg("2026-11-11T00:00:00Z"))*3600,3.0,
            delta=0.05)

    def test_reject_naive_epoch(self):
        with self.assertRaises(ValueError): read_epoch("2026-11-11T12:00:00")
        with self.assertRaises(ValueError): read_epoch("2026-11-11T12:00:00+03:00")
        with self.assertRaises(ValueError): gmst_deg("2026-11-11T12:00:00Z",5)

    def test_datetime_utc_results(self):
        self.assertEqual(date_at("2026-11-11T23:59:59Z",2),
                         "2026-11-12T00:00:01.000Z")

    def test_time_window_and_radio(self):
        validate_windows(self.cfg,0.5)
        self.assertFalse(within_task_window(self.jobs[0],49.5))
        self.assertTrue(within_task_window(self.jobs[0],82.5))
        self.assertFalse(within_task_window(self.jobs[0],120.5))
        self.assertTrue(radio_window_open(self.cfg,10))
        self.assertFalse(radio_window_open(self.cfg,25))
        self.assertTrue(radio_window_open(self.cfg,80))

    def test_reject_overlap_and_invalid_planned_bounds(self):
        c=copy.deepcopy(self.cfg)
        c["downlink_windows"][1]["start_s"]=20
        with self.assertRaises(ValueError): validate_windows(c,0.5)
        c=copy.deepcopy(self.cfg)
        c["tasks"][0]["planned_end_s"]=201
        with self.assertRaises(ValueError): validate_windows(c,0.5)

    def test_capture_plan_vs_actual(self):
        x=schedule_task_record(self.jobs[0],[82.5],"completed",None)
        self.assertEqual(x["actual_first_capture_delay_s"],32.5)
        self.assertTrue(x["last_capture_within_plan"])
        y=schedule_task_record(self.jobs[0],[],"planned_window_missed","no_ground_access")
        self.assertIsNone(y["actual_first_capture_s"])
        self.assertEqual(y["reason"],"no_ground_access")

    def test_geodetic_wgs84_subpoint(self):
        a=6378137.0;b=a*(1-1/298.257223563)
        identity=[[1,0,0],[0,1,0],[0,0,1]]
        lat,lon,h=wgs84_subpoint_from_position([a+500000,0,0],identity)
        self.assertAlmostEqual(lat,0.,places=7)
        self.assertAlmostEqual(lon,0.,places=7)
        self.assertAlmostEqual(h,500000,places=3)
        lat,lon,h=wgs84_subpoint_from_position([0,0,b+500000],identity)
        self.assertAlmostEqual(lat,90.,places=6)
        self.assertAlmostEqual(h,500000,places=2)


HAS_GEO=importlib.util.find_spec("shapely") is not None and importlib.util.find_spec("pyproj") is not None

@unittest.skipUnless(HAS_GEO,"shapely/pyproj tested in Mission05 scientific CI; Python baseline stays dependency-free")
class CoverageTests(unittest.TestCase):
    def test_wgs84_laea_union_no_double_count(self):
        from experiments.mission_03.coverage import polygon_coverage
        regions={"R":{"polygon_lat_lon_deg":[
            [-0.05,-0.05],[-0.05,0.05],[0.05,0.05],[0.05,-0.05]]}}
        jobs=[{"id":"S","kind":"strip","region_id":"R"}]
        track=[{"t_s":0,"lat_deg":0,"lon_deg":-0.01},
               {"t_s":1,"lat_deg":0,"lon_deg":0},
               {"t_s":2,"lat_deg":0,"lon_deg":0.01}]
        sample={"t_s":1,"task":"S","lat_deg":0,"lon_deg":0,
                "swath_width_m":500,"altitude_m":500000}
        first=polygon_coverage(regions,jobs,[sample],track,1.0)
        double=polygon_coverage(regions,jobs,[sample,sample],track,1.0)
        m=first["regions"]["R"]["covered_area_m2"]
        self.assertGreater(m,300000)
        self.assertLess(m,750000)
        self.assertAlmostEqual(double["regions"]["R"]["covered_area_m2"],m,places=4)
        self.assertLess(first["regions"]["R"]["covered_percent"],100)

    def test_directional_gate_rejects_false_upstream_circle(self):
        from experiments.mission_03.coverage import LiveStripGeometry
        from experiments.mission_03.swath_geometry import swath_intersects_region
        polygon=[[-0.01,0.01],[-0.01,0.02],[0.01,0.02],[0.01,0.01]]
        gate=LiveStripGeometry({"R":{"polygon_lat_lon_deg":polygon}})
        # Old radial-distance gate falsely permits imaging because its
        # 3-km circle touches a region 2.2 km AHEAD of the satellite.
        # The physical camera strip is cross-track and does not.
        circular,_,_=swath_intersects_region(
            0,-0.01,500000,0.68755,polygon,6378137)
        self.assertTrue(circular)
        area=gate.cell_overlap_m2(
            "R",(0,-0.015),(0,-0.01),6000,predict_next=True)
        self.assertEqual(area,0.)
        # When the true predicted track enters the region it must permit.
        area2=gate.cell_overlap_m2(
            "R",(0,0),(0,0.005),6000,predict_next=True)
        self.assertGreater(area2,10000.)
        # The actual footprint at the earlier sample is still outside.
        actual=gate.cell_overlap_m2(
            "R",(0,0),(0,0.005),6000,predict_next=False)
        self.assertEqual(actual,0.)

    def test_live_gate_actual_and_report_footprint_agree(self):
        from experiments.mission_03.coverage import LiveStripGeometry,polygon_coverage
        polygon=[[-0.01,0.01],[-0.01,0.02],[0.01,0.02],[0.01,0.01]]
        regions={"R":{"polygon_lat_lon_deg":polygon}}
        gate=LiveStripGeometry(regions)
        previous=(0,0.004)
        actual=(0,0.011)
        overlap=gate.cell_overlap_m2(
            "R",previous,actual,6000,predict_next=False)
        self.assertGreater(overlap,10000.)
        trajectory=[
            {"t_s":0,"lat_deg":previous[0],"lon_deg":previous[1]},
            {"t_s":1,"lat_deg":actual[0],"lon_deg":actual[1]}]
        task=[{"id":"S","kind":"strip","region_id":"R"}]
        lines=[{"t_s":1,"task":"S","lat_deg":actual[0],
                "lon_deg":actual[1],"swath_width_m":6000,
                "altitude_m":500000}]
        report=polygon_coverage(regions,task,lines,trajectory,1.)
        self.assertAlmostEqual(
            report["regions"]["R"]["covered_area_m2"],
            overlap,delta=max(1.,overlap*.001))

    def test_coverage_zero_when_no_basilisk_data(self):
        from experiments.mission_03.coverage import polygon_coverage
        regions={"R":{"polygon_lat_lon_deg":[[0,0],[0,0.1],[0.1,0.1],[0.1,0]]}}
        result=polygon_coverage(regions,[{"id":"S","kind":"strip","region_id":"R"}],
                                [],[{"t_s":0,"lat_deg":0,"lon_deg":0},
                                    {"t_s":1,"lat_deg":0,"lon_deg":0.01}],1.0)
        self.assertEqual(result["regions"]["R"]["covered_area_m2"],0)
        self.assertEqual(result["regions"]["R"]["covered_percent"],0)

if __name__=="__main__":
    unittest.main()
