"""Mission 03: sequential, physically actuated Earth-observation data cycle.

A genuine Basilisk simulation runs ONE spacecraft throughout:
    orbital/attitude dynamics + physical RWs + target geometry + camera +
    partitioned storage + packet ground transmitter + eclipse/solar/battery.
After the first verified camera product, the target and storage partition are
changed, as in scenarioGroundLocationImaging, while the rigid-body and wheel
states continue without reinitializing. Battery and device modes are evaluated
from actual Basilisk battery telemetry every control_step_s.

This is an intentionally minimal TWO-target physical EXECUTOR, not an
optimization algorithm and not a flight-certified satellite model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from Basilisk.simulation import groundLocation, planetEphemeris, spacecraft
from Basilisk.utilities import (
    SimulationBaseClass, macros, orbitalMotion, simHelpers, simIncludeGravBody,
    vizSupport,
)

from experiments.adcs_01.kinematics import true_boresight_error_deg
from experiments.adcs_02.integration import attach as attach_adcs
from experiments.mission_01.integration import attach as attach_datachain
from experiments.power_01.integration import attach as attach_power
from experiments.power_01.analysis import analyse_run as analyse_power
from experiments.mission_03.logic import validate, permitted, stage_for_sample
from nirs_satellite.input_paths import input_path

ROOT = Path(__file__).resolve().parents[2]
EXEC_CONFIG = input_path("mission_execution")


def _read(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _site(target, location):
    location.specifyLocation(
        math.radians(target["lat_deg"]), math.radians(target["lon_deg"]),
        float(target["altitude_m"]),
    )
    location.minimumElevation = math.radians(target["minimum_elevation_deg"])
    location.maximumRange = float(target["maximum_range_m"])


def _ground_r_fixed(site, earth_radius):
    lat, lon = map(math.radians, (site["lat_deg"], site["lon_deg"]))
    radius = earth_radius + float(site["altitude_m"])
    return np.array([radius * math.cos(lat) * math.cos(lon),
                     radius * math.cos(lat) * math.sin(lon),
                     radius * math.sin(lat)], dtype=float)


def _draw_vizard(sim, process, task, sc, grav_earth, data, targets, earth_radius,
                 output_name, cadence):
    if not vizSupport.vizFound:
        raise RuntimeError("Basilisk Vizard interface not available")
    from Basilisk.architecture import messaging
    from Basilisk.simulation import vizInterface

    viz_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "NIRS_Satellite" / "viz"
    if not str(viz_dir).isascii():
        raise RuntimeError("Vizard playback path must be ASCII-only on Windows")
    viz_dir.mkdir(parents=True, exist_ok=True)
    bin_path = viz_dir / f"{output_name}.bin"
    if bin_path.exists():
        bin_path.unlink()

    viz_task = task
    if cadence > 0.5:
        viz_task = "mission03VizTask"
        process.addTask(sim.CreateNewTask(viz_task, macros.sec2nano(cadence)), taskPriority=0)

    sensor = vizInterface.GenericSensor()
    sensor.label = "MISSION03 REAL CAMERA COMMAND"
    sensor.r_SB_B = [0.0, 0.0, 0.2]
    sensor.normalVector = [0.0, 0.0, 1.0]
    sensor.fieldOfView.push_back(math.radians(20))
    sensor.color = vizInterface.IntVector([255, 100, 20, 160])
    rdr = messaging.DeviceCmdMsgReader()
    rdr.subscribeTo(data.capture_command_msg)
    sensor.genericSensorCmdInMsg = rdr

    link = vizInterface.Transceiver()
    link.label = "GROUND LINK"
    link.r_SB_B = [0.2, 0.0, 0.0]
    link.normalVector = [1.0, 0.0, 0.0]
    link.fieldOfView = math.radians(40)
    link.color = vizInterface.IntVector([0, 220, 110, 255])
    lrdr = messaging.DataNodeUsageMsgReader()
    lrdr.subscribeTo(data.transmitter_data_msg)
    link.transceiverStateInMsgs.push_back(lrdr)

    store = vizInterface.GenericStorage()
    store.label = "PHYSICAL MEMORY - TWO PARTITIONS"
    store.units = "bits"
    store.color = vizInterface.IntVector([0, 130, 240, 255, 230, 80, 30, 255])
    store.thresholds = vizInterface.IntVector([50])
    srdr = messaging.DataStorageStatusMsgReader()
    srdr.subscribeTo(data.storage_status_msg)
    store.dataStorageStateInMsg = srdr

    viz = vizSupport.enableUnityVisualization(
        sim, viz_task, sc, saveFile=str(bin_path),
        genericSensorList=sensor, transceiverList=link, genericStorageList=store,
    )
    if viz is None:
        raise RuntimeError("Unable to initialize Basilisk Vizard recording")
    vizSupport.setInstrumentGuiSetting(
        viz, showGenericSensorLabels=True,
        showTransceiverLabels=True, showGenericStoragePanel=True,
    )
    parent = str(grav_earth.displayName)
    if parent not in [str(b.bodyName) for b in viz.gravBodyInformation]:
        raise RuntimeError("Vizard planet label does not match physical Earth")
    for j, site in enumerate(targets):
        r = _ground_r_fixed(site, earth_radius)
        vizSupport.addLocation(
            viz, stationName=site["id"], parentBodyName=parent,
            r_GP_P=r, gHat_P=r/np.linalg.norm(r),
            label=f"IMAGE TARGET {j+1}", markerScale=15,
            color=[255, 0, 255, 255] if j == 0 else [255, 160, 30, 255],
            isHidden=False, fieldOfView=math.radians(160), range=2e6,
        )
    st = data.config["downlink"]["ground_station"]
    radius = earth_radius + float(st["altitude_m"])
    st_pos = _ground_r_fixed({
        "lat_deg":st["latitude_deg"],"lon_deg":st["longitude_deg"],
        "altitude_m":st["altitude_m"]
    }, earth_radius)
    vizSupport.addLocation(
        viz, stationName=st["name"], parentBodyName=parent,
        r_GP_P=st_pos, gHat_P=st_pos/np.linalg.norm(st_pos),
        label="GROUND STATION", markerScale=10,
        color=[0, 220, 100, 255], isHidden=False,
        fieldOfView=math.radians(160), range=2e6,
    )
    vizSupport.createTargetLine(
        viz, toBodyName=targets[0]["id"],
        lineColor=[255, 0, 255, 255],
    )
    viz.settings.showLocationLabels = 1
    viz.settings.showLocationCones = -1
    viz.settings.showLocationCommLines = -1
    return bin_path, viz


def _plot(out, t, battery, memory, error, panel, switch_t):
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    axes[0].plot(t/60, error, label="Actual boresight error (deg)")
    axes[0].set_ylabel("Angle, deg")
    axes[0].set_ylim(bottom=0)
    axes[1].plot(t/60, memory/8e6, label="Onboard memory (MB)")
    axes[1].set_ylabel("Stored, MB")
    axes[2].plot(t/60, battery, label="Basilisk battery (Wh)")
    axes[2].plot(t/60, panel, label="Basilisk solar panel (W)")
    axes[2].set_ylabel("Battery Wh / solar W")
    axes[2].set_xlabel("Synthetic elapsed time (min)")
    for ax in axes:
        if switch_t is not None:
            ax.axvline(switch_t/60, color="tab:orange", linestyle="--",
                       label="Target switch")
        ax.legend(loc="best")
        ax.grid(alpha=0.3)
    fig.suptitle("Mission 03: physically actuated two-target satellite")
    fig.tight_layout()
    fig.savefig(out/"mission03_dataflow.png", dpi=160)
    plt.close(fig)


def _write_outputs(
    out, cfg, sources, sim_time, state, target_rec, target_access,
    adcs, data, power, events, switch_t, granted_segments,
    first_generation_count, bin_path, step, radio_rate, battery_reserve,
):
    t = np.asarray(data.instrument_data_rec.times(), dtype=float)*1e-9
    x = np.asarray(state.r_BN_N, dtype=float)
    sigma = np.asarray(state.sigma_BN, dtype=float)
    target_pos = np.asarray(target_rec.r_LN_N, dtype=float)
    ta = np.asarray(target_access.hasAccess, dtype=int)
    sa = np.asarray(data.station_access_rec.hasAccess, dtype=int)
    gen = np.asarray(data.instrument_data_rec.baudRate, dtype=float)
    tx = np.asarray(data.transmitter_rec.baudRate, dtype=float)
    stored = np.asarray(data.storage_rec.storageLevel, dtype=float)
    battery = np.asarray(power.battery_rec.storageLevel, dtype=float)/3600
    panel = np.asarray(power.panel_rec.netPower, dtype=float)
    rws = np.asarray(adcs.rw_recorder.wheelSpeeds, dtype=float)
    guid_err = np.asarray(adcs.guidance_recorder.sigma_BR, dtype=float)
    guid_rate = np.asarray(adcs.guidance_recorder.omega_BR_B, dtype=float)
    n=len(t)
    expected_vector = (x,sigma,target_pos,guid_err,guid_rate)
    expected_scalar = (ta,sa,gen,tx,stored,battery,panel)
    if n < 3 or any(v.shape!=(n,3) for v in expected_vector):
        raise AssertionError("Mission03 physical vector recorders are not aligned")
    if any(v.shape!=(n,) for v in expected_scalar) or rws.shape!=(n,3):
        raise AssertionError(f"Mission03 scalar or wheel recorders are not aligned: n={n}, scalars={[a.shape for a in expected_scalar]}, wheels={rws.shape}")
    for rec in (state,target_rec,target_access,adcs.rw_recorder,
                adcs.guidance_recorder,data.station_access_rec,
                data.instrument_data_rec,data.transmitter_rec,
                data.storage_rec,power.battery_rec,power.panel_rec):
        if not np.allclose(np.asarray(rec.times())*1e-9,t,atol=1e-8,rtol=0):
            raise AssertionError("Non-synchronous Basilisk recorder")
    if not np.all(np.isfinite(battery)) or not np.all(np.isfinite(stored)):
        raise AssertionError("Nonfinite power or onboard memory")
    dt=float(np.median(np.diff(t)))
    if not np.allclose(np.diff(t),dt,atol=1e-8,rtol=0):
        raise AssertionError("Basilisk physics time step changed during retargeting")
    phases=np.array([stage_for_sample(float(v),switch_t,step) for v in t],dtype=int)
    pointing=np.array([true_boresight_error_deg(s,p,q,
                        adcs.config["instrument_boresight_B"])
                       for s,p,q in zip(sigma,x,target_pos)])
    shots=np.flatnonzero(gen>1e-6)
    capture_count=[int(np.count_nonzero(phases[shots]==idx)) for idx in (0,1)]
    capture_times=[t[shots[phases[shots]==i]].tolist() for i in (0,1)]
    expected_bits = float(data.config["capture"]["product_bytes"])*8
    generated=float(np.sum(gen[1:]*np.diff(t)))
    downlinked=float(np.sum(-tx[1:]*np.diff(t)))
    residual=float(stored[-1])
    conservation=float(generated-downlinked-residual)
    available=any(e["event"]=="retarget" for e in events)
    speed_rpm=rws / macros.RPM
    maximum_rpm=float(np.max(np.abs(speed_rpm)))
    limit_rpm=float(adcs.config["rw"]["max_speed_rpm"])
    max_error_at_capture=max((pointing[i] for i in shots), default=float("nan"))
    maximum_capture_error_deg=math.degrees(
        4*math.atan(float(data.config["capture"]["maximum_attitude_mrp_error"])))
    safety_violation=bool(np.min(battery)<battery_reserve-1e-3)
    checks={
        "two_distinct_captures":capture_count==[1,1],
        "physical_target_retargeted":available and switch_t is not None,
        "actual_boresight_at_capture":bool(np.all(pointing[shots]<=maximum_capture_error_deg + 0.1)) if len(shots) else False,
        "capture_in_window":bool(np.all(ta[shots]>0)) if len(shots) else False,
        "wheel_speed_saturated_safely":maximum_rpm<=limit_rpm+3,
        "physical_memory_capacity":bool(np.all(stored>=-1) and np.max(stored)<=8*data.config["storage"]["capacity_bytes"]+1),
        "power_bus_within_capacity":bool(np.min(battery)>=-1e-3 and np.max(battery)<=power.config["battery_capacity_wh"]+1e-3),
        "reserve_not_crossed":not safety_violation,
        "station_access_when_transmitting":bool(np.all(sa[tx<0]>0)),
        "nonnegative_generation_and_tx":bool(np.all(gen>=-1e-8) and np.all(tx<=1e-8)),
        "data_conserved":abs(conservation)<=max(1.0,2*step*radio_rate),
        "generated_two_products":abs(generated-2*expected_bits)<1,
        "same_step_throughout":abs(dt-step)<1e-8,
    }
    # Audit telemetry exports, including the physical wheel states and actual
    # geometric error for EVERY capture in the multi-target mission.
    with (out/"mission03_states.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f)
        w.writerow(["time_s","task_id","target_access","station_access",
                    "actual_boresight_error_deg","generated_rate_bps",
                    "downlink_rate_bps","stored_bits","battery_wh",
                    "panel_w","rw_1_rpm","rw_2_rpm","rw_3_rpm"])
        for i in range(n):
            w.writerow([float(t[i]), cfg["tasks"][phases[i]]["id"],
                        int(ta[i]),int(sa[i]),float(pointing[i]),
                        float(gen[i]),float(tx[i]),float(stored[i]),
                        float(battery[i]),float(panel[i]),*map(float,speed_rpm[i])])
    power_analysis=analyse_power(times=t,components=power,output=out)
    power_analysis["limitations"]=[
        "Power sink loads are switched between simulation segments according to model schedule",
        "Actual Basilisk battery, eclipse and solar panel states are integrated continuously",
        "A bus load remains always on; power reserve gating is discrete and not flight hardware",
        "The Sun vector and all electrical parameters are synthetic"
    ]
    (out/"power_summary.json").write_text(json.dumps(power_analysis,ensure_ascii=False,indent=2),encoding="utf-8")
    _plot(out,t,battery,stored,pointing,panel,switch_t)
    with (out/"mission03_events.json").open("w",encoding="utf-8") as f:
        json.dump(events,f,ensure_ascii=False,indent=2)
    result={
        "model":"Basilisk physically actuated 2-target sequential executor",
        "provenance":"SYNTHETIC; NOT an identified space vehicle",
        "tasks":[{"id":task["id"],"capture_count":capture_count[j],
                  "capture_times_s":[round(float(x),3) for x in capture_times[j]]}
                 for j,task in enumerate(cfg["tasks"])],
        "sample_count":n,"step_s":dt,"duration_s":float(t[-1]),
        "retarget_time_s":switch_t,
        "actual_capture_max_boresight_error_deg":max_error_at_capture,
        "physical_wheel_max_rpm":maximum_rpm,
        "physical_wheel_limit_rpm":limit_rpm,
        "generated_bits":generated,"transmitted_bits":downlinked,
        "final_stored_bits":residual,"max_stored_bits":float(np.max(stored)),
        "memory_capacity_bits":8*data.config["storage"]["capacity_bytes"],
        "conservation_error_bits":conservation,
        "battery_initial_wh":float(battery[0]),"battery_final_wh":float(battery[-1]),
        "battery_minimum_wh":float(np.min(battery)),
        "battery_reserve_wh":float(battery_reserve),
        "power_enabled_segments":int(sum(granted_segments)),
        "power_disabled_segments":int(len(granted_segments)-sum(granted_segments)),
        "station_tx_samples":int(np.sum(tx<0)),
        "checks":checks,
        "checks_passed":all(checks.values()),
        "vizard_file":str(bin_path) if bin_path else None,
        "vizard_created":bool(bin_path and bin_path.is_file() and bin_path.stat().st_size>0),
        "sources_sha256":sources,
        "limitations":cfg["model_limitations"],
        "research_status":"Tested physical executor for TWO sequential tasks; optimizer is not included."
    }
    (out/"mission03_summary.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(
        description="Mission03: one Basilisk spacecraft, two physical target switches")
    parser.add_argument("--config",type=Path,default=EXEC_CONFIG)
    parser.add_argument("--duration-hours",type=float)
    parser.add_argument("--output-name",default="mission03_two_targets")
    parser.add_argument("--viz-mode",choices=("file","off"),default="file")
    parser.add_argument("--viz-step-s",type=float,default=10)
    parser.add_argument("--require-two-captures",action="store_true",
                        help="Fail CI if two physically generated products were not observed")
    args=parser.parse_args()
    import re
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}",args.output_name):
        parser.error("Use ASCII alphanumeric output name, starting with letter")
    cfg,sha=_read(args.config)
    orbit,orbit_sha=_read(input_path("orbit"))
    geo,geo_sha=_read(input_path("earth_target"))
    adcs_cfg,adcs_sha=_read(input_path("adcs_wheels"))
    power_cfg,power_sha=_read(input_path("power"))
    mission_cfg,mission_sha=_read(input_path("camera_storage_radio"))
    step=float(mission_cfg["capture"]["assumed_exposure_duration_s"])
    validate(cfg,step_s=step,
             product_name=mission_cfg["capture"]["product_name"],
             partition_name=mission_cfg["storage"]["partition_name"],
             product_bytes=int(mission_cfg["capture"]["product_bytes"]),
             storage_bytes=int(mission_cfg["storage"]["capacity_bytes"]),
             initial_energy_wh=float(power_cfg["battery_initial_wh"]))
    hours=cfg["default_duration_hours"] if args.duration_hours is None else args.duration_hours
    if not math.isfinite(hours) or not (0.2<=hours<=2):
        parser.error("Mission03 supports 0.2–2 simulation hours")
    horizon_s=hours*3600
    if not math.isclose(horizon_s/step,round(horizon_s/step),abs_tol=1e-8):
        parser.error("Horizon must be a multiple of physical step")
    control_step=float(cfg["control_step_s"])
    if args.viz_mode=="file" and (
            args.viz_step_s<step or
            not math.isclose(args.viz_step_s/step,round(args.viz_step_s/step),abs_tol=1e-8)):
        parser.error("Vizard step must be a whole multiple of physical step")
    out=ROOT/"results"/args.output_name
    if out.exists():
        parser.error("Existing result directory: choose a new --output-name")
    out.mkdir(parents=True)

    # Original Ground01 Earth + orbit composition is kept exactly: same
    # synthetic epoch, same planet orientation for geometry and Vizard.
    sim=SimulationBaseClass.SimBaseClass()
    process=sim.CreateNewProcess("mission03PhysicalProcess")
    task="mission03PhysicalTask"
    process.addTask(sim.CreateNewTask(task,macros.sec2nano(step)),taskPriority=100)
    eph=planetEphemeris.PlanetEphemeris()
    eph.ModelTag="Mission03SyntheticRotatingEarth"
    eph.setPlanetNames(planetEphemeris.StringVector(["earth"]))
    pe=planetEphemeris.ClassicElements()
    pe.a=149597870700.0
    pe.e=0.0
    pe.i=pe.Omega=pe.omega=pe.f=0.0
    eph.planetElements=planetEphemeris.classicElementVector([pe])
    eph.zeroBase="earth"
    e=geo["earth"]
    eph.rightAscension=planetEphemeris.DoubleVector([math.radians(e["rotational_pole_ra_deg"])])
    eph.declination=planetEphemeris.DoubleVector([math.radians(e["rotational_pole_dec_deg"])])
    eph.lst0=planetEphemeris.DoubleVector([math.radians(e["initial_sidereal_angle_deg"])])
    eph.rotRate=planetEphemeris.DoubleVector([float(e["rotation_rate_rad_s"])])
    sim.AddModelToTask(task,eph,ModelPriority=200)

    sc=spacecraft.Spacecraft()
    sc.ModelTag="NIRS-MISSION03-PHYSICAL"
    sc.hub.mHub=float(orbit["hub_mass_kg"])
    ix,iy,iz=map(float,orbit["hub_inertia_diag_kg_m2"])
    sc.hub.IHubPntBc_B=simHelpers.np2EigenMatrix3d(
        [ix,0.,0.,0.,iy,0.,0.,0.,iz])
    sc.hub.r_BcB_B=[[0.],[0.],[0.]]
    gravity=simIncludeGravBody.gravBodyFactory()
    earth=gravity.createEarth()
    earth.isCentralBody=True
    earth.planetBodyInMsg.subscribeTo(eph.planetOutMsgs[0])
    gravity.addBodiesTo(sc)
    el=orbitalMotion.ClassicElements()
    el.a=float(orbit["reference_radius_m"])+float(orbit["initial_altitude_m"])
    el.e=float(orbit["eccentricity"])
    el.i=math.radians(orbit["inclination_deg"])
    el.Omega=math.radians(orbit["raan_deg"])
    el.omega=math.radians(orbit["argument_of_periapsis_deg"])
    el.f=math.radians(orbit["true_anomaly_deg"])
    sc.hub.r_CN_NInit,sc.hub.v_CN_NInit=orbitalMotion.elem2rv(float(earth.mu),el)
    sim.AddModelToTask(task,sc,ModelPriority=150)

    first=cfg["tasks"][0]
    target=groundLocation.GroundLocation()
    target.ModelTag="MISSION03_ActiveTarget"
    target.planetRadius=float(orbit["reference_radius_m"])
    _site(first,target)
    target.addSpacecraftToModel(sc.scStateOutMsg)
    target.planetInMsg.subscribeTo(eph.planetOutMsgs[0])
    sim.AddModelToTask(task,target,ModelPriority=100)

    adcs=attach_adcs(sim,task,sc,target,orbit,step)
    data=attach_datachain(
        sim,task,sc,eph.planetOutMsgs[0],float(orbit["reference_radius_m"]),
        target.accessOutMsgs[0],adcs.guidance_msg,step,profile="nominal")
    # Create second Basilisk partition BEFORE initialization.
    data.storage_model.addPartition(cfg["tasks"][1]["id"])
    data.transmitter_model.numBuffers=2
    power=attach_power(sim,task,sc,eph.planetOutMsgs[0],mission_loads_always_on=False)
    sc_rec=sc.scStateOutMsg.recorder()
    ground_rec=target.currentGroundStateOutMsg.recorder()
    access_rec=target.accessOutMsgs[0].recorder()
    for rec in (sc_rec,ground_rec,access_rec):
        sim.AddModelToTask(task,rec,ModelPriority=0)

    bin_path=None
    viz=None
    if args.viz_mode=="file":
        bin_path,viz=_draw_vizard(sim,process,task,sc,earth,data,cfg["tasks"],
                                  float(orbit["reference_radius_m"]),
                                  args.output_name,float(args.viz_step_s))
    print(f"MISSION 03 physical dynamics: {horizon_s:.1f}s at {step}s; "
          f"two targets; battery gate every {control_step:g}s",flush=True)
    sim.InitializeSimulation()
    events=[{"t_s":0.0,"event":"target_assigned","task":first["id"]}]
    phase=0
    switch_t=None
    current_energy=float(power_cfg["battery_initial_wh"])
    allowed=True
    granted_segments=[]
    observations=0
    last_sample=0
    t=0.0
    old_armed=None
    old_tx=None
    while t < horizon_s - 1e-8:
        duration=min(control_step,horizon_s-t)
        # Read the integrated battery energy from the previous simulation
        # segment (not a fictitious independent battery state).
        desired=permitted(
            current_energy,reserve_wh=float(cfg["reserve_wh"]),
            guard_wh=float(cfg["reserve_guard_wh"]),
            hysteresis_wh=float(cfg["battery_reenable_hysteresis_wh"]),
            previously_permitted=allowed)
        if desired!=allowed:
            events.append({"t_s":round(t,6),"event":"power_enabled" if desired else "power_safe_mode",
                           "battery_wh":round(current_energy,6)})
        allowed=desired
        waiting=phase<2
        camera_on=allowed and waiting
        backlogged=(last_sample>0 and float(data.storage_rec.storageLevel[-1])>=
                    8*int(mission_cfg["downlink"]["packet_bytes"]))
        contact=(last_sample>0 and bool(data.station_access_rec.hasAccess[-1]))
        radio_on=allowed and backlogged and contact
        data.controller_model.attErrTolerance=(
            float(mission_cfg["capture"]["maximum_attitude_mrp_error"])
            if camera_on else -1.0)
        data.controller_model.rateErrTolerance=(
            float(mission_cfg["capture"]["maximum_rate_error_rad_s"])
            if camera_on else -1.0)
        data.transmitter_model.nodeBaudRate=(
            -float(mission_cfg["downlink"]["rate_bits_per_s"]) if radio_on else 0.)
        power.imaging_sink.powerStatus=1 if camera_on else 0
        power.transmitter_sink.powerStatus=1 if radio_on else 0
        granted_segments.append(allowed)
        if camera_on!=old_armed:
            events.append({"t_s":round(t,6),"event":"camera_armed" if camera_on else "camera_off"})
            old_armed=camera_on
        if radio_on!=old_tx:
            events.append({"t_s":round(t,6),"event":"radio_on" if radio_on else "radio_off"})
            old_tx=radio_on
        end=t+duration
        sim.ConfigureStopTime(macros.sec2nano(end))
        sim.ExecuteSimulation()
        rate=np.asarray(data.instrument_data_rec.baudRate,dtype=float)
        ts=np.asarray(data.instrument_data_rec.times(),dtype=float)*1e-9
        hit=np.flatnonzero(rate[last_sample:]>0) + last_sample
        if len(hit):
            if len(hit)!=1 or phase>=2:
                raise AssertionError(f"Unexpected extra Basilisk exposure in phase {phase}")
            time=float(ts[hit[0]])
            task_cfg=cfg["tasks"][phase]
            events.append({"t_s":time,"event":"captured","task":task_cfg["id"],
                           "produced_bits":8*mission_cfg["capture"]["product_bytes"]})
            observations+=1
            if phase==0:
                # This is the documented Basilisk pattern: change GroundLocation
                # and reset the one-shot instrument controller. No reinit of
                # spacecraft, attitude, wheels, battery, memory or transmitter.
                second=cfg["tasks"][1]
                _site(second,target)
                data.instrument_model.nodeDataName=second["id"]
                data.controller_model.imaged=0
                switch_t=end
                phase=1
                events.append({"t_s":round(end,6),"event":"retarget",
                               "from":first["id"],"to":second["id"]})
                if viz is not None:
                    vizSupport.targetLineList[0].toBodyName=second["id"]
                    vizSupport.targetLineList[0].lineColor=vizSupport.toRGBA255("orange")
                    vizSupport.updateTargetLineList(viz)
            elif phase==1:
                phase=2
        last_sample=len(rate)
        current_energy=float(power.battery_rec.storageLevel[-1])/3600
        t=end
    source_hashes={
        str(path.relative_to(ROOT)):checksum for path,checksum in (
            (args.config.resolve(),sha),(input_path("orbit"),orbit_sha),
            (input_path("earth_target"),geo_sha),(input_path("adcs_wheels"),adcs_sha),
            (input_path("power"),power_sha),(input_path("camera_storage_radio"),mission_sha))
    }
    result=_write_outputs(
        out,cfg,source_hashes,t,sc_rec,ground_rec,access_rec,
        adcs,data,power,events,switch_t,granted_segments,observations,
        bin_path,step,float(mission_cfg["downlink"]["rate_bits_per_s"]),
        float(cfg["reserve_wh"]))
    print("MISSION03 PHYSICAL:",json.dumps({
        "captures":[task["capture_count"] for task in result["tasks"]],
        "retarget_s":result["retarget_time_s"],
        "generated_MB":round(result["generated_bits"]/8e6,4),
        "transmitted_MB":round(result["transmitted_bits"]/8e6,4),
        "battery_minimum_wh":round(result["battery_minimum_wh"],4),
        "checks_passed":result["checks_passed"],
        "vizard":result["vizard_file"],
    },ensure_ascii=False),flush=True)
    if args.require_two_captures and not result["checks_passed"]:
        raise SystemExit(f"MISSION03 ACCEPTANCE FAILED: {result['checks']}")


if __name__=="__main__":
    main()
