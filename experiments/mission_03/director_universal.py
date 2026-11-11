"""Generic fixed-order Basilisk task execution (NOT a planner).

This low-priority Basilisk SysModel observes actual camera, storage, battery and
spacecraft state. It commands the next target and camera/radio power for the
NEXT physical time step. Strip mode continuously updates a nadir groundLocation
from the *physical* spacecraft ephemeris and true planet-fixed rotation.
"""
from __future__ import annotations
import math
from Basilisk.architecture import sysModel
from Basilisk.utilities import macros

from experiments.mission_03.logic import permitted
from experiments.mission_03.swath_geometry import (
    ground_point_from_position, wgs84_subpoint_from_position,
    swath_intersects_region, great_circle_distance_m,
)
from experiments.mission_03.timeline import task_window, radio_window_open, within_task_window
from experiments.mission_03.coverage import LiveStripGeometry

class UniversalMissionDirector(sysModel.SysModel):
    def __init__(self, *, cfg, regions, data, target, power, spacecraft,
                 planet_msg, earth_radius_m, step_s, nominal_att_tol,
                 nominal_rate_tol, nominal_radio_bps, default_product_bytes):
        super().__init__()
        self.ModelTag="NIRS_UniversalPhysicalExecutor"
        self.cfg=cfg
        self.regions=regions
        self.data=data
        self.target=target
        self.power=power
        self.spacecraft=spacecraft
        self.planet_msg=planet_msg
        self.radius=float(earth_radius_m)
        self.step=float(step_s)
        # Cached WGS84 footprint polygons for both physical permission and
        # postflight report, avoiding spherical circular-gate false positives.
        self._footprints=LiveStripGeometry(regions)
        self.tasks=list(cfg["tasks"])
        self.phase=0
        self.nominal_att_tol=float(nominal_att_tol)
        self.nominal_rate_tol=float(nominal_rate_tol)
        self.nominal_radio_bps=float(nominal_radio_bps)
        self.default_product_bytes=int(default_product_bytes)
        self.events=([{"t_s":0.,"event":"task_assigned","task":self.tasks[0]["id"]}]
                     if self.tasks else [{"t_s":0.,"event":"idle_program"}])
        self.capture_count={v["id"]:0 for v in self.tasks}
        self.capture_times={v["id"]:[] for v in self.tasks}
        self.task_status={v["id"]:"pending" for v in self.tasks}
        self.task_reason={v["id"]:None for v in self.tasks}
        self.blocked={v["id"]:{} for v in self.tasks}
        self.lines=[]
        self.ground_track=[]
        self.switch_times=[]
        self.power_enabled_segments=[]
        self.allowed=True
        self._next_control_ns=0
        self._last_capture_ns=None
        self._previous_strip_fix=None
        self._previous_strip_time=None
        self._last_camera=None
        self._last_radio=None
        self._strip_eligible=False
        self._last_subpoint=None

    def Reset(self,CurrentSimNanos):
        self._next_control_ns=0
        self._last_capture_ns=None
        return super().Reset(CurrentSimNanos)

    def _task(self):
        return self.tasks[self.phase] if self.phase<len(self.tasks) else None

    def _assign_task(self,t):
        job=self._task()
        if job is None:
            self.events.append({"t_s":t,"event":"program_completed"})
            return
        if job.get("kind","point")=="point":
            self.target.specifyLocation(
                macros.D2R*float(job["lat_deg"]),macros.D2R*float(job["lon_deg"]),
                float(job["altitude_m"]))
            self.target.minimumElevation=macros.D2R*float(job["minimum_elevation_deg"])
            self.target.maximumRange=float(job["maximum_range_m"])
        else:
            # The first concrete nadir update follows in the same director step.
            self.target.minimumElevation=0.0
            self.target.maximumRange=-1.0
        self.data.instrument_model.nodeDataName=job["id"]
        self.data.controller_model.imaged=0
        self._previous_strip_fix=None
        self._previous_strip_time=None
        self.events.append({"t_s":t,"event":"task_assigned","task":job["id"]})
        self.switch_times.append(t)

    def _advance(self,t,status):
        job=self._task()
        if job is None:
            return
        self.task_status[job["id"]]=status
        if status!="completed":
            blockers=self.blocked[job["id"]]
            ordered=sorted(blockers, key=lambda s:(-blockers[s],s))
            self.task_reason[job["id"]]=(
                "planned_window_elapsed" if status=="planned_window_missed" else
                "deadline_elapsed" if status=="deadline_missed" else status)
            if ordered:
                self.task_reason[job["id"]]+="; main_observed_blocker="+ordered[0]
        self.events.append({"t_s":t,"event":"task_completed" if status=="completed" else "task_skipped",
                            "task":job["id"],"status":status,
                            "reason":self.task_reason[job["id"]],
                            "observed_blockers":self.blocked[job["id"]],
                            "samples":self.capture_count[job["id"]]})
        self.phase+=1
        self._assign_task(t)

    def finalize(self,simulation_horizon_s:float):
        """Finalize pending jobs when time stops, without falsely crediting an image."""
        while self.phase<len(self.tasks):
            job=self.tasks[self.phase]
            name=job["id"]
            samples=self.capture_count[name]
            minimum=int(job.get("min_samples",1))
            if job.get("kind","point")=="strip" and samples>=minimum:
                status="completed"
                reason=None
            else:
                status="horizon_incomplete"
                counts=self.blocked[name]
                observed=sorted(counts,key=lambda q:(-counts[q],q))
                reason="simulation_horizon"
                if observed:
                    reason+="; main_observed_blocker="+observed[0]
            self.task_status[name]=status
            self.task_reason[name]=reason
            self.events.append({
                "t_s":float(simulation_horizon_s),
                "event":"task_completed" if status=="completed" else "task_skipped",
                "task":name,"status":status,"reason":reason,
                "observed_blockers":dict(self.blocked[name]),
                "samples":samples
            })
            self.phase+=1

    def _subpoint(self):
        r=self.spacecraft.scStateOutMsg.read().r_BN_N
        rot=self.planet_msg.read().J20002Pfix
        if self.cfg.get("epoch_utc"):
            return wgs84_subpoint_from_position(r,rot)
        return ground_point_from_position(r,rot,self.radius)

    def UpdateState(self,CurrentSimNanos):
        t=float(CurrentSimNanos)*macros.NANO2SEC
        job=self._task()
        lat_trace,lon_trace,h_trace=self._subpoint()
        self.ground_track.append({"t_s":t,"lat_deg":lat_trace,"lon_deg":lon_trace,
                                  "altitude_m":h_trace,"task":job["id"] if job else None})
        baud=float(self.data.instrument_model.nodeDataOutMsg.read().baudRate)

        # Only a REAL Basilisk DataNodeUsage positive data impulse qualifies as
        # an image line. The director never fabricates successful captures.
        if job is not None and baud>1e-8 and self._last_capture_ns!=CurrentSimNanos:
            self._last_capture_ns=CurrentSimNanos
            name=job["id"]
            self.capture_count[name]+=1
            self.capture_times[name].append(t)
            kind=job.get("kind","point")
            if kind=="strip":
                lat,lon,h=lat_trace,lon_trace,h_trace
                region=self.regions[job["region_id"]]
                overlap,distance,width=swath_intersects_region(
                    lat,lon,h,float(job["fov_cross_track_deg"]),
                    region["polygon_lat_lon_deg"],self.radius)
                previous=self.ground_track[-2] if len(self.ground_track)>1 else None
                measured_overlap=self._footprints.cell_overlap_m2(
                    job["region_id"],
                    (previous["lat_deg"],previous["lon_deg"]) if previous else None,
                    (lat,lon),width,predict_next=False)
                if measured_overlap<=0:
                    # Never raise an exception through Basilisk's C++/SWIG
                    # UpdateState callback: it may tear down the interpreter
                    # with a Windows access violation. Preserve real camera
                    # data and report an engineering verification failure
                    # OUTSIDE ExecuteSimulation in report_universal.py.
                    self.events.append({"t_s":t,
                        "event":"strip_line_geometry_mismatch",
                        "task":name,"actual_overlap_m2":measured_overlap})
                length=0.0
                if self._previous_strip_fix is not None and self._previous_strip_time is not None:
                    lag=t-self._previous_strip_time
                    if lag<=self.step*1.5:
                        length=great_circle_distance_m(
                            self._previous_strip_fix,(lat,lon),self.radius)
                self._previous_strip_fix=(lat,lon)
                self._previous_strip_time=t
                record={"t_s":t,"task":name,"lat_deg":lat,"lon_deg":lon,
                        "altitude_m":h,"region_signed_distance_m":distance,
                        "swath_width_m":width,"along_track_m":length,
                        "instant_footprint_overlap_m2":measured_overlap,
                        "approx_area_m2":length*width,"data_bits":baud*self.step}
                self.lines.append(record)
                self.events.append({"t_s":t,"event":"strip_line","task":name,
                                    "line":self.capture_count[name],
                                    "data_bits":baud*self.step})
                if self.capture_count[name]>=int(job["max_samples"]):
                    self._advance(t,"completed")
            else:
                self.events.append({"t_s":t,"event":"point_captured",
                                    "task":name,"data_bits":baud*self.step})
                self._advance(t,"completed")

        # Expired tasks are skipped, never represented as physical captures.
        while self._task() is not None:
            current=self._task()
            _,planned_end=task_window(current)
            if t<=min(planned_end,float(current["deadline_s"]))+1e-8:
                break
            samples=self.capture_count[current["id"]]
            minimum=int(current.get("min_samples",1))
            success=current.get("kind","point")=="strip" and samples>=minimum
            status=("completed" if success else
                    "planned_window_missed" if planned_end<float(current["deadline_s"])-1e-8
                    else "deadline_missed")
            self._advance(t,status)

        job=self._task()
        # Direct physical subpoint and footprint recomputed every dynamics tick.
        self._strip_eligible=False
        if job is not None and job.get("kind","point")=="strip":
            lat,lon,h=lat_trace,lon_trace,h_trace
            self._last_subpoint=(lat,lon,h)
            self.target.specifyLocation(macros.D2R*lat,macros.D2R*lon,0.)
            reg=self.regions[job["region_id"]]
            # The camera command applies to the NEXT Basilisk dynamics step.
            # Test the predicted narrow rectangular next strip-cell against
            # the region, not a symmetric circular radius around current nadir.
            from experiments.mission_03.swath_geometry import nadir_footprint_width_m
            width=nadir_footprint_width_m(h,float(job["fov_cross_track_deg"]))
            previous=self.ground_track[-2] if len(self.ground_track)>1 else None
            next_overlap=self._footprints.cell_overlap_m2(
                job["region_id"],
                (previous["lat_deg"],previous["lon_deg"]) if previous else None,
                (lat,lon),width,predict_next=True)
            # Avoid spurious grazing-boundary captures caused by one-step
            # extrapolation errors of a few metres near the polygon boundary.
            self._strip_eligible=next_overlap>10_000.

        # Battery policy is sampled at the declared slower 5s cadence. Camera
        # geometry still changes each 0.5s, not every 5s.
        if CurrentSimNanos>=self._next_control_ns:
            self._next_control_ns=CurrentSimNanos+macros.sec2nano(
                float(self.cfg["control_step_s"]))
            energy=float(self.power.battery_model.batPowerOutMsg.read().storageLevel)/3600.
            authorized=permitted(
                energy,reserve_wh=float(self.cfg["reserve_wh"]),
                guard_wh=float(self.cfg["reserve_guard_wh"]),
                hysteresis_wh=float(self.cfg["battery_reenable_hysteresis_wh"]),
                previously_permitted=self.allowed)
            if authorized!=self.allowed:
                self.events.append({"t_s":t,"event":"power_enabled" if authorized else "power_safe_mode",
                                    "battery_wh":energy})
            self.allowed=authorized
            self.power_enabled_segments.append(authorized)

        # Actual shared onboard buffer gates the next imager acquisition.
        storage_bits=float(self.data.storage_model.storageUnitDataOutMsg.read().storageLevel)
        cap_bits=float(self.data.config["storage"]["capacity_bytes"])*8
        packet_bits=abs(float(self.data.transmitter_model.packetSize))
        station_access=bool(self.data.station_model.accessOutMsgs[0].read().hasAccess)
        kind=job.get("kind","point") if job is not None else ""
        product_bytes=(int(job.get("sample_bytes",0)) if kind=="strip" else
                       int(job.get("product_bytes",self.default_product_bytes))
                       if job is not None else self.default_product_bytes)
        # Commands issued after Basilisk module update apply to the NEXT
        # physical sample. Test that next sample, not the old state timestamp.
        next_camera_time=t+self.step
        camera_window=job is not None and within_task_window(job,next_camera_time)
        memory_ok=storage_bits+8*product_bytes<=cap_bits+1
        geometry_ok=kind!="strip" or self._strip_eligible
        imaging_allowed=(job is not None and self.allowed and camera_window
                         and geometry_ok and memory_ok)
        if job is not None:
            reasons=[]
            if not self.allowed: reasons.append("energy_reserve")
            if not camera_window: reasons.append("outside_planned_camera_window")
            if not memory_ok: reasons.append("onboard_memory_full")
            if not geometry_ok: reasons.append("swath_outside_region")
            if imaging_allowed and not bool(self.target.accessOutMsgs[0].read().hasAccess):
                reasons.append("no_ground_target_access")
            for reason in reasons:
                counts=self.blocked[job["id"]]
                counts[reason]=counts.get(reason,0)+1
        self.data.controller_model.attErrTolerance=(
            self.nominal_att_tol if imaging_allowed else -1.)
        self.data.controller_model.rateErrTolerance=(
            self.nominal_rate_tol if imaging_allowed else -1.)
        if job is not None:
            self.data.instrument_model.nodeBaudRate=float(product_bytes)*8/self.step
        if kind=="strip" and imaging_allowed:
            # Re-arm each line. The actual Basilisk access/attitude gate still
            # decides whether the camera produces bytes this step.
            self.data.controller_model.imaged=0
        radio_allowed=(self.allowed and station_access
                       and radio_window_open(self.cfg,t+self.step)
                       and storage_bits>=packet_bits)
        self.data.transmitter_model.nodeBaudRate=(
            -self.nominal_radio_bps if radio_allowed else 0.)
        self.power.imaging_sink.powerStatus=1 if imaging_allowed else 0
        self.power.transmitter_sink.powerStatus=1 if radio_allowed else 0
        if imaging_allowed!=self._last_camera:
            self.events.append({"t_s":t,"event":"camera_armed" if imaging_allowed else "camera_off",
                                "task":job["id"] if job else None})
            self._last_camera=imaging_allowed
        if radio_allowed!=self._last_radio:
            self.events.append({"t_s":t,"event":"radio_on" if radio_allowed else "radio_off"})
            self._last_radio=radio_allowed
