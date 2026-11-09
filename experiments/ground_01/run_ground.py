"""Ground 01: calculate one rotating-Earth ground target access window with Basilisk.

Runs a SYNTHETIC Earth-centred, point-mass circular-orbit experiment, using
Basilisk spacecraft + planetEphemeris + groundLocation. Produces traceable
CSV/PNG/JSON and independent checks of geometry and rotation.

From repository root:
  .venv\\Scripts\\python.exe -m experiments.ground_01.run_ground
"""
from __future__ import annotations

from nirs_satellite.input_paths import input_path

import argparse
import csv
import json
import hashlib
import math
import os
from importlib.metadata import version
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from Basilisk.simulation import groundLocation, planetEphemeris, spacecraft, simSynch
from Basilisk.architecture import astroConstants
from Basilisk.utilities import (
    SimulationBaseClass, macros, orbitalMotion, simHelpers, simIncludeGravBody, vizSupport
)

from experiments.ground_01.geometry import (
    access_windows, elevation_from_inertial, rotate_z, norm3
)
from experiments.ground_01.run_settings import build_plan
from experiments.ground_01.run_reporting import write_run_explanation
from nirs_satellite.orbit.analytical import orbital_period_s

ROOT = Path(__file__).resolve().parents[2]
CONF = input_path("earth_target")

def draw_plots(times: np.ndarray, elevation_deg: np.ndarray, range_km: np.ndarray,
               access: np.ndarray, limit_deg: float, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(times/60, elevation_deg, label="Ground target elevation")
    ax.axhline(limit_deg, linestyle="--", color="tab:orange",
               label=f"Visibility threshold {limit_deg:g} deg")
    ax.fill_between(times/60, elevation_deg, limit_deg,
                    where=access, color="tab:green", alpha=0.18, interpolate=False,
                    label="Access available")
    ax.set(xlabel="Elapsed simulation time (min)", ylabel="Elevation angle (deg)",
           title="Ground 01 — rotating Earth, target visibility")
    ax.legend()
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(output/"elevation.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(times/60, range_km, label="Geometric distance (including hidden satellite)")
    # The straight-line range is still defined even when Earth blocks the line
    # of sight. Highlight only samples passing the 10-degree access threshold.
    if np.any(access):
        ax.plot(times[access]/60, range_km[access], color="tab:green",
                linewidth=3, label="Accessible samples")
    ax.set(xlabel="Elapsed simulation time (min)", ylabel="Slant range (km)",
           title="Ground-to-spacecraft distance; green = visible samples")
    ax.legend()
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(output/"slant_range.png",dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ground 01: rotating Earth and geometric visibility"
    )
    parser.add_argument(
        "--viz", action="store_true",
        help="Also create a Vizard playback with the rotating Earth and target marker",
    )
    parser.add_argument(
        "--payload", action="store_true",
        help="Use Basilisk instrument to make one synthetic 1 MB product under ideal pointing",
    )
    parser.add_argument(
        "--adcs", action="store_true",
        help="Track rotating-Earth target with simulated rigid-body attitude and ideal torque",
    )
    parser.add_argument("--power", action="store_true",
                        help="Attach Basilisk eclipse, body-fixed solar panel and simpleBattery diagnostic")
    parser.add_argument(
        "--actuator", choices=["ideal", "rw"], default="ideal",
        help="ADCS actuation: ideal external torque (baseline) or physical Basilisk reaction wheels",
    )
    parser.add_argument(
        "--mission", action="store_true",
        help="One-spacecraft data cycle: real pointing, synthetic capture, memory and ground downlink",
    )
    parser.add_argument("--multi-target", action="store_true",
                        help="Mission03: actual Basilisk wheel retargeting and multiple synthetic products")
    parser.add_argument(
        "--mission-profile", choices=["nominal", "slow_link"], default="nominal",
        help="Mission 01 fixed-rate profile for controlled delivery comparison",
    )
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--duration-hours", type=float, help="Simulation horizon in hours")
    duration.add_argument("--duration-days", type=float, help="Simulation horizon in days")
    duration.add_argument("--orbits", type=float, help="Simulation horizon in orbital periods")
    parser.add_argument("--step-s", type=float, help="Dynamics time step; overrides config")
    parser.add_argument("--viz-mode", choices=["off", "file", "live"], default="off",
                        help="Off, pre-record .bin, or live Vizard DirectComm")
    parser.add_argument("--viz-step-s", type=float,
                        help="Vizard update cadence (seconds); integer multiple of dynamics step")
    parser.add_argument("--speed", type=float,
                        help="Live mode only: simulated seconds per real second (default 50)")
    parser.add_argument("--live-port", type=int, default=5556,
                        help="Local Vizard DirectComm TCP port; live mode only")
    parser.add_argument("--output-name", default="ground_01",
                        help="Result folder name under results/ (ASCII-safe)")
    parser.add_argument("--allow-large-run", action="store_true",
                        help="Explicitly permit >100000 saved integration samples")
    parser.add_argument("--plan-only", action="store_true",
                        help="Show validated plan and quit without running simulation")
    args = parser.parse_args()
    if args.multi_target and (not args.mission or args.actuator!="rw" or not args.power):
        parser.error("--multi-target requires --mission --actuator rw --power")
    multi_cfg=None
    multi_targets=None
    if args.multi_target:
        from experiments.mission_03.parameters import validate as validate_multi
        path_multi=input_path("multitarget_demo")
        multi_cfg=json.loads(path_multi.read_text(encoding="utf-8"))
        multi_targets=multi_cfg["targets"]
    if args.mission and (args.adcs or args.payload):
        parser.error("--mission includes physical ADCS and its own synthetic payload; do not combine modes")
    if not args.mission and args.mission_profile != "nominal":
        parser.error("--mission-profile requires --mission")
    if args.adcs and args.payload:
        parser.error("--adcs and legacy --payload are separate; use --mission for integrated physical pointing")
    if args.actuator == "rw" and not (args.adcs or args.mission):
        parser.error("--actuator rw requires --adcs or --mission")
    ground_config_bytes = CONF.read_bytes()
    params=json.loads(ground_config_bytes)
    ground_config_sha=hashlib.sha256(ground_config_bytes).hexdigest()
    orbit_config=(CONF.parent/params["orbit_config_path"]).resolve()
    orbit_config_bytes=orbit_config.read_bytes()
    orbit_cfg=json.loads(orbit_config_bytes)
    orbit_config_sha=hashlib.sha256(orbit_config_bytes).hexdigest()
    if not str(params["provenance"]).startswith("SYNTHETIC"):
        raise ValueError("First Ground experiment must be marked synthetic")
    default_step=float(params["step_s"])
    n_orbits=float(params["number_of_orbits"])
    if not (math.isfinite(default_step) and default_step>0 and
            math.isfinite(n_orbits) and n_orbits>0):
        raise ValueError("Invalid integration step or simulation horizon")
    tcfg=params["target"]
    ecfg=params["earth"]
    radius=float(orbit_cfg["reference_radius_m"])
    omega=float(ecfg["rotation_rate_rad_s"])
    latitude=math.radians(float(tcfg["latitude_deg"]))
    longitude=math.radians(float(tcfg["longitude_deg"]))
    min_elevation=math.radians(float(tcfg["minimum_elevation_deg"]))
    if not (radius>0 and -math.pi/2<=latitude<=math.pi/2 and
            -math.pi<=longitude<=math.pi and 0<=min_elevation<math.pi/2 and omega>0):
        raise ValueError("Invalid Earth/ground geometric parameters")
    # The same Basilisk Earth gravitational parameter is used by
    # gravBodyFactory.createEarth() later during the actual integration.
    planned_period = orbital_period_s(
        radius + float(orbit_cfg["initial_altitude_m"]),
        float(astroConstants.MU_EARTH) * 1e9,
    )
    plan = build_plan(
        default_orbits=n_orbits,
        orbit_period_s=planned_period,
        default_step_s=default_step,
        duration_hours=args.duration_hours,
        duration_days=args.duration_days,
        orbits=args.orbits,
        step_s=(0.5 if (args.adcs or args.mission) and args.step_s is None else args.step_s),
        viz_mode=args.viz_mode,
        legacy_viz=args.viz,
        viz_step_s=args.viz_step_s,
        speed=args.speed,
        live_port=args.live_port,
        output_name=(("mission_01" if args.mission else "adcs_01")
                     if (args.adcs or args.mission) and args.output_name == "ground_01"
                     else args.output_name),
        allow_large_run=args.allow_large_run,
    )
    preview = {
        **plan.as_dict(),
        "input_preview": {
            "orbit_altitude_m": float(orbit_cfg["initial_altitude_m"]),
            "orbit_inclination_deg": float(orbit_cfg["inclination_deg"]),
            "orbit_eccentricity": float(orbit_cfg["eccentricity"]),
            "orbit_raan_deg": float(orbit_cfg["raan_deg"]),
            "earth_reference_radius_m": radius,
            "earth_rotation_rate_rad_s": omega,
            "target_latitude_deg": float(tcfg["latitude_deg"]),
            "target_longitude_deg": float(tcfg["longitude_deg"]),
            "minimum_elevation_deg": float(tcfg["minimum_elevation_deg"]),
        },
        "input_sources": {
            "orbit": "inputs/physical/orbit.json (synthetic)",
            "earth_and_target": "inputs/physical/earth_target.json (synthetic)",
            "time_overrides": "CLI values replace horizon, step or Vizard cadence ONLY",
        },
        "accuracy_note": "Two-body circular orbit + synthetic Earth rotation, no UTC",
    }
    if args.adcs or args.mission:
        if args.actuator == "rw":
            from experiments.adcs_02.integration import CONFIG as ADCS_CONFIG, validate_adcs_config
        else:
            from experiments.adcs_01.integration import CONFIG as ADCS_CONFIG, validate_adcs_config
        adcs_preview = json.loads(ADCS_CONFIG.read_text(encoding="utf-8"))
        validate_adcs_config(adcs_preview, plan.step_s)
        preview["input_preview"]["adcs_initial_sigma_BN_mrp"] = adcs_preview["initial_sigma_BN_mrp"]
        preview["input_preview"]["adcs_initial_omega_BN_B_rad_s"] = adcs_preview["initial_omega_BN_B_rad_s"]
        preview["input_preview"]["adcs_boresight_B"] = adcs_preview["instrument_boresight_B"]
        preview["input_preview"]["adcs_feedback_K_Nm"] = adcs_preview["feedback_gain_K_Nm"]
        preview["input_preview"]["adcs_rate_gain_P_Nm_s"] = adcs_preview["rate_gain_P_Nm_s"]
        preview["input_sources"]["adcs"] = (
            "inputs/physical/adcs_wheels.json (synthetic RW)" if args.actuator == "rw"
            else "inputs/physical/adcs_ideal_legacy.json (synthetic ideal torque)"
        )
        preview["accuracy_note"] += (
            "; Basilisk reaction wheels with synthetic torque/speed limits and ideal nav"
            if args.actuator == "rw"
            else "; ideal navigation and unlimited torque (no real actuators)"
        )
    if args.mission:
        from experiments.mission_01.integration import CONFIG_BY_PROFILE, validate_config as validate_mission
        mission_path = CONFIG_BY_PROFILE[args.mission_profile]
        mission_preview = json.loads(mission_path.read_text(encoding="utf-8"))
        validate_mission(mission_preview, plan.step_s)
        preview["input_preview"]["mission_product_bytes"] = mission_preview["capture"]["product_bytes"]
        preview["input_preview"]["mission_storage_capacity_bytes"] = mission_preview["storage"]["capacity_bytes"]
        preview["input_preview"]["mission_radio_rate_bits_s"] = mission_preview["downlink"]["rate_bits_per_s"]
        preview["input_preview"]["mission_ground_station"] = mission_preview["downlink"]["ground_station"]
        preview["input_sources"]["mission"] = f"experiments/mission_01/{mission_path.name} (synthetic)"
        preview["mission_profile"] = args.mission_profile
        preview["accuracy_note"] += "; fixed rate ideal radio and bit queue, no packet errors or receiver"
    if args.payload:
        payload_path = input_path("payload_demo_legacy")
        payload_plan = json.loads(payload_path.read_text(encoding="utf-8"))
        preview["input_preview"]["synthetic_payload_bytes_per_product"] = payload_plan["bytes_per_product"]
        preview["input_sources"]["payload"] = "inputs/physical/payload_demo_legacy.json (synthetic)"
    if args.power:
        power_path = input_path("power")
        preview["input_preview"]["power_config"] = json.loads(power_path.read_text(encoding="utf-8"))
        preview["input_sources"]["power"] = str(power_path)
        preview["accuracy_note"] += "; Basilisk solar panel, conical eclipse and battery WITHOUT brownout gate"
    if args.plan_only:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return
    print(
        "INPUTS (synthetic) from config.json: "
        f"altitude={preview['input_preview']['orbit_altitude_m']:g} m; "
        f"inclination={preview['input_preview']['orbit_inclination_deg']:g} deg; "
        f"target=({preview['input_preview']['target_latitude_deg']:g}, "
        f"{preview['input_preview']['target_longitude_deg']:g}) deg; "
        f"elevation limit={preview['input_preview']['minimum_elevation_deg']:g} deg",
        flush=True,
    )
    print("Origin: inputs/physical/orbit.json + earth_target.json; no real UTC epoch", flush=True)
    step = plan.step_s
    if args.multi_target:
        common_hardware={
            "mission":json.loads(input_path("camera_storage_radio").read_text(encoding="utf-8")),
            "power":json.loads(input_path("power").read_text(encoding="utf-8")),
        }
        validate_multi(multi_cfg,common_hardware,step)
        preview["mission03"]={"targets":multi_targets,"reserve_wh":multi_cfg["energy_reserve_wh"]}
    output = ROOT / "results" / plan.output_name
    output.mkdir(parents=True, exist_ok=True)
    if plan.expected_samples >= 10_000:
        print(
            f"Long simulation: approximately {plan.expected_samples} saved states "
            f"and {plan.expected_viz_frames} visualization frames",
            flush=True,
        )

    sim=SimulationBaseClass.SimBaseClass()
    process=sim.CreateNewProcess("groundProcess")
    task="groundTask"
    process.addTask(sim.CreateNewTask(task,macros.sec2nano(step)),taskPriority=100)

    # A single Earth ephemeris with Earth as zeroBase is *centred* on Earth:
    # no heliocentric translation; orientation rotates with constant omega.
    # The epoch/prime meridian are synthetic: no real UTC association.
    eph=planetEphemeris.PlanetEphemeris()
    eph.ModelTag="SyntheticRotatingEarth"
    eph.setPlanetNames(planetEphemeris.StringVector(["earth"]))
    eph_elem=planetEphemeris.ClassicElements()
    eph_elem.a=149597870700.0  # m, nominal AU; cancels under zeroBase="earth"
    eph_elem.e=0.0
    eph_elem.i=eph_elem.Omega=eph_elem.omega=eph_elem.f=0.0
    eph.planetElements=planetEphemeris.classicElementVector([eph_elem])
    eph.zeroBase="earth"
    eph.rightAscension=planetEphemeris.DoubleVector(
        [math.radians(float(ecfg["rotational_pole_ra_deg"]))])
    eph.declination=planetEphemeris.DoubleVector(
        [math.radians(float(ecfg["rotational_pole_dec_deg"]))])
    eph.lst0=planetEphemeris.DoubleVector(
        [math.radians(float(ecfg["initial_sidereal_angle_deg"]))])
    eph.rotRate=planetEphemeris.DoubleVector([omega])
    sim.AddModelToTask(task,eph,ModelPriority=200)

    sat=spacecraft.Spacecraft()
    sat.ModelTag="NIRS-GROUND-01"
    sat.hub.mHub=float(orbit_cfg["hub_mass_kg"])
    inertia=[float(x) for x in orbit_cfg["hub_inertia_diag_kg_m2"]]
    sat.hub.IHubPntBc_B=simHelpers.np2EigenMatrix3d(
        [inertia[0],0,0,0,inertia[1],0,0,0,inertia[2]])
    sat.hub.r_BcB_B=[[0.0],[0.0],[0.0]]

    grav=simIncludeGravBody.gravBodyFactory()
    earth=grav.createEarth()
    earth.isCentralBody=True
    # A single physical Earth orientation drives BOTH groundLocation and Vizard.
    # The point-mass gravity remains Earth-centred under zeroBase="earth".
    earth.planetBodyInMsg.subscribeTo(eph.planetOutMsgs[0])
    grav.addBodiesTo(sat)
    mu=float(earth.mu)
    elements=orbitalMotion.ClassicElements()
    elements.a=radius+float(orbit_cfg["initial_altitude_m"])
    elements.e=float(orbit_cfg["eccentricity"])
    elements.i=math.radians(orbit_cfg["inclination_deg"])
    elements.Omega=math.radians(orbit_cfg["raan_deg"])
    elements.omega=math.radians(orbit_cfg["argument_of_periapsis_deg"])
    elements.f=math.radians(orbit_cfg["true_anomaly_deg"])
    r0,v0=orbitalMotion.elem2rv(mu,elements)
    sat.hub.r_CN_NInit=r0
    sat.hub.v_CN_NInit=v0
    sim.AddModelToTask(task,sat,ModelPriority=150)

    target=groundLocation.GroundLocation()
    target.ModelTag=str(multi_targets[0]["name"] if multi_targets else tcfg["name"])
    target.planetRadius=radius
    target.minimumElevation=min_elevation
    target.maximumRange=float(tcfg["maximum_range_m"])
    if multi_targets:
        first=multi_targets[0]
        target.minimumElevation=math.radians(float(first["minimum_elevation_deg"]))
        target.specifyLocation(math.radians(float(first["latitude_deg"])),
                               math.radians(float(first["longitude_deg"])),
                               float(first["altitude_m"]))
    else:
        target.specifyLocation(latitude,longitude,float(tcfg["altitude_m"]))
    target.addSpacecraftToModel(sat.scStateOutMsg)
    target.planetInMsg.subscribeTo(eph.planetOutMsgs[0])
    sim.AddModelToTask(task,target,ModelPriority=100)

    adcs_components = None
    if args.adcs or args.mission:
        if args.actuator == "rw":
            from experiments.adcs_02.integration import attach as attach_adcs
        else:
            from experiments.adcs_01.integration import attach as attach_adcs
        adcs_components = attach_adcs(
            sim, task, sat, target, orbit_cfg, step
        )

    sc_rec=sat.scStateOutMsg.recorder()
    ground_rec=target.currentGroundStateOutMsg.recorder()
    access_rec=target.accessOutMsgs[0].recorder()
    for recorder in (sc_rec,ground_rec,access_rec):
        sim.AddModelToTask(task,recorder,ModelPriority=0)

    mission_components = None
    if args.mission:
        from experiments.mission_01.integration import attach as attach_mission
        mission_components = attach_mission(
            sim, task, sat, eph.planetOutMsgs[0], radius,
            target.accessOutMsgs[0], adcs_components.guidance_msg, step,
            profile=args.mission_profile,physical_targets=multi_targets
        )

    power_components = None
    if args.power:
        from experiments.power_01.integration import attach as attach_power
        power_components = attach_power(
            sim, task, sat, eph.planetOutMsgs[0],
            mission_loads_always_on=(mission_components is not None),
        )

    payload_cfg = None
    payload_command_rec = None
    payload_data_rec = None
    payload_config_sha = None
    if args.payload:
        from experiments.payload_01.integration import attach
        payload_cfg, payload_command_rec, payload_data_rec, payload_config_sha = attach(
            sim, task, target.accessOutMsgs[0], step
        )

    # Vizard is optional so its native file writer never blocks basic physics.
    # Explicit .bin in ASCII-only LOCALAPPDATA avoids the Windows Cyrillic path
    # failure found in Orbit 01. The target uses the SAME spherical planet-fixed
    # coordinates as groundLocation.specifyLocation(), not an independently
    # guessed geodetic/WGS84 point.
    viz_file = None
    viz_status = "disabled"
    if plan.viz_mode != "off":
        if not vizSupport.vizFound:
            raise RuntimeError("Installed Basilisk lacks vizInterface support")
        viz_task = task
        if plan.viz_step_s > step:
            # Physics and geometry remain on the original step_s task.
            # This second, lower-priority task only updates visualization.
            viz_task = "groundVizTask"
            process.addTask(
                sim.CreateNewTask(viz_task, macros.sec2nano(plan.viz_step_s)),
                taskPriority=0,
            )
        if plan.viz_mode == "file":
            viz_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "NIRS_Satellite" / "viz"
            if not str(viz_dir).isascii():
                raise RuntimeError(
                    "Vizard playback path is not ASCII-only. Choose an ASCII-only "
                    "LOCALAPPDATA directory or run without --viz."
                )
            viz_dir.mkdir(parents=True, exist_ok=True)
            viz_file = viz_dir / f"{plan.output_name}.bin"
            # Never report a previous run's file as successfully created.
            if viz_file.exists():
                viz_file.unlink()
        if plan.viz_mode == "live":
            clock = simSynch.ClockSynch()
            clock.ModelTag = "LiveSimulationClock"
            clock.accelFactor = float(plan.live_speed)
            sim.AddModelToTask(viz_task, clock, ModelPriority=10)
        # Optional instrument/radio/storage panels expose the actual Basilisk
        # data messages instead of a hand-drawn or invented dashboard.
        vizard_features = {}
        if mission_components is not None:
            from Basilisk.simulation import vizInterface
            from Basilisk.architecture import messaging

            sensor = vizInterface.GenericSensor()
            sensor.label = "SYNTHETIC IMAGE COMMAND"
            sensor.r_SB_B = [0.0, 0.0, 0.2]
            sensor.normalVector = [0.0, 0.0, 1.0]
            sensor.fieldOfView.push_back(math.radians(20.0))
            sensor.color = vizInterface.IntVector([255, 100, 20, 160])
            sensor_reader = messaging.DeviceCmdMsgReader()
            sensor_reader.subscribeTo(mission_components.capture_command_msg)
            sensor.genericSensorCmdInMsg = sensor_reader

            radio_hud = vizInterface.Transceiver()
            radio_hud.label = "SYNTHETIC RADIO LINK"
            radio_hud.r_SB_B = [0.2, 0.0, 0.0]
            radio_hud.normalVector = [1.0, 0.0, 0.0]
            radio_hud.fieldOfView = math.radians(40)
            radio_hud.color = vizInterface.IntVector([0, 220, 110, 255])
            radio_reader = messaging.DataNodeUsageMsgReader()
            radio_reader.subscribeTo(mission_components.transmitter_data_msg)
            radio_hud.transceiverStateInMsgs.push_back(radio_reader)

            disk_hud = vizInterface.GenericStorage()
            disk_hud.label = "SYNTHETIC ONBOARD MEMORY"
            disk_hud.units = "bits"
            disk_hud.color = vizInterface.IntVector([0, 130, 240, 255, 230, 80, 30, 255])
            disk_hud.thresholds = vizInterface.IntVector([50])
            disk_reader = messaging.DataStorageStatusMsgReader()
            disk_reader.subscribeTo(mission_components.storage_status_msg)
            disk_hud.dataStorageStateInMsg = disk_reader

            vizard_features = {
                "genericSensorList": sensor,
                "transceiverList": radio_hud,
                "genericStorageList": disk_hud,
            }
        viz = vizSupport.enableUnityVisualization(
            sim, viz_task, sat,
            saveFile=str(viz_file) if viz_file is not None else None,
            liveStream=plan.viz_mode == "live",
            **vizard_features,
        )
        if mission_components is not None and viz is not None:
            vizSupport.setInstrumentGuiSetting(
                viz, showGenericSensorLabels=True,
                showTransceiverLabels=True, showGenericStoragePanel=True,
            )
        if viz is None:
            raise RuntimeError("Could not initialize Vizard export/stream")
        if plan.viz_mode == "live":
            # Restrict the development DirectComm connection to this computer.
            viz.reqComProtocol = "tcp"
            viz.reqComAddress = "127.0.0.1"
            viz.reqPortNumber = str(plan.live_port)
        radial = radius + float(tcfg["altitude_m"])
        r_ground_fixed = np.array([
            radial * math.cos(latitude) * math.cos(longitude),
            radial * math.cos(latitude) * math.sin(longitude),
            radial * math.sin(latitude),
        ], dtype=float)
        normal_fixed = r_ground_fixed / np.linalg.norm(r_ground_fixed)
        # CRITICAL: Basilisk distinguishes planetName="earth_planet_data"
        # from displayName="earth".  Vizard's GravBodyInfo.bodyName is built
        # from displayName, so a location using planetName is orphaned and
        # not visibly attached to the rendered Earth.
        planet_display_name = str(earth.displayName)
        available_viz_bodies = [str(body.bodyName) for body in viz.gravBodyInformation]
        if planet_display_name not in available_viz_bodies:
            raise RuntimeError(
                "Vizard display body mismatch: "
                f"{planet_display_name!r} absent from {available_viz_bodies!r}"
            )
        vizSupport.addLocation(
            viz,
            stationName=str(multi_targets[0]["name"] if multi_targets else tcfg["name"]),
            parentBodyName=planet_display_name,
            r_GP_P=r_ground_fixed,
            gHat_P=normal_fixed,
            label="SYNTHETIC TARGET 1" if multi_targets else "TARGET 14N 43E",
            markerScale=15.0,
            color=[255, 0, 255, 255],
            isHidden=False,
            fieldOfView=math.radians(160.0),
            range=2_000_000.0,
        )
        if multi_targets:
            for dest in multi_targets[1:]:
                phi=math.radians(float(dest["latitude_deg"]))
                lam=math.radians(float(dest["longitude_deg"]))
                rad=radius+float(dest["altitude_m"])
                xyz=np.array([rad*math.cos(phi)*math.cos(lam),rad*math.cos(phi)*math.sin(lam),
                              rad*math.sin(phi)],dtype=float)
                vizSupport.addLocation(
                    viz,stationName=str(dest["name"]),parentBodyName=planet_display_name,
                    r_GP_P=xyz,gHat_P=xyz/np.linalg.norm(xyz),
                    label=str(dest["id"]),markerScale=15.0,
                    color=[235,150,50,255],isHidden=False,
                    fieldOfView=math.radians(160),range=2_000_000.0,
                )
        if mission_components is not None:
            station = mission_components.config["downlink"]["ground_station"]
            st_lat = math.radians(float(station["latitude_deg"]))
            st_lon = math.radians(float(station["longitude_deg"]))
            st_rad = radius + float(station["altitude_m"])
            st_fixed = np.array([
                st_rad * math.cos(st_lat) * math.cos(st_lon),
                st_rad * math.cos(st_lat) * math.sin(st_lon),
                st_rad * math.sin(st_lat),
            ], dtype=float)
            vizSupport.addLocation(
                viz, stationName=str(station["name"]),
                parentBodyName=planet_display_name,
                r_GP_P=st_fixed,
                gHat_P=st_fixed/np.linalg.norm(st_fixed),
                label="SYNTHETIC GROUND STATION", markerScale=10.0,
                color=[0, 220, 100, 255], isHidden=False,
                fieldOfView=math.radians(160), range=2_000_000.0,
            )
        # The marker and label are visual guides, NOT proof of actual imaging.
        # The target line is always drawn, including when the Earth occludes
        # the target: physical access remains defined by access.csv.
        vizSupport.createTargetLine(
            viz, toBodyName=str(multi_targets[0]["name"] if multi_targets else tcfg["name"]),
            lineColor=[255, 0, 255, 255],
        )
        viz.settings.showLocationLabels = 1
        viz.settings.showLocationCones = -1
        viz.settings.showLocationCommLines = -1
        viz_location_names = [str(location.stationName) for location in viz.locations]
        if str(multi_targets[0]["name"] if multi_targets else tcfg["name"]) not in viz_location_names:
            raise RuntimeError(
                f"Vizard target marker was not registered: {viz_location_names!r}"
            )
        if plan.viz_mode == "file":
            viz_status = "file playback requested; visible ground marker attached"
        else:
            viz_status = (
                f"live DirectComm tcp://127.0.0.1:{plan.live_port}; "
                f"clock acceleration {plan.live_speed:g}x"
            )

    period=orbital_period_s(elements.a,mu)
    if not math.isclose(period, planned_period, rel_tol=1e-12):
        raise RuntimeError("Basilisk Earth mu differs from documented planning constant")
    print(
        f"Ground 01 configured: {plan.horizon_s:.3f} s ({plan.duration_source}), "
        f"physics {step:g} s, Vizard {plan.viz_mode} every {plan.viz_step_s:g} s.",
        flush=True,
    )
    print("Initializing Basilisk...",flush=True)
    sim.InitializeSimulation()
    print("Computing ground access with rotating Earth...",flush=True)
    multi_events=[]
    sample_target_ids=None
    if args.multi_target:
        from experiments.mission_03.supervisor import Supervisor
        supervisor=Supervisor(tuple(s["id"] for s in multi_targets),
                              float(multi_cfg["energy_reserve_wh"]))
        sample_target_ids=[]
        elapsed=0.0
        interval=float(multi_cfg["command_interval_s"])
        nominal_tx=-float(mission_components.config["downlink"]["rate_bits_per_s"])
        # Conservative reserve for one command interval of all mission loads.
        reserve_guard=(
            float(power_components.config["base_load_w"])+
            float(power_components.config["imaging_load_w"])+
            float(power_components.config["transmitter_load_w"])
        )*interval/3600.0
        while elapsed+step*0.5<plan.horizon_s:
            active_idx=supervisor.active_index
            next_stop=min(plan.horizon_s,elapsed+interval)
            sim.ConfigureStopTime(macros.sec2nano(next_stop))
            sim.ExecuteSimulation()
            size=len(mission_components.instrument_data_rec.baudRate)
            new_count=size-len(sample_target_ids)
            if new_count<0:
                raise AssertionError("Lost recorded simulation samples")
            sample_target_ids.extend([multi_targets[active_idx]["id"]]*new_count)
            elapsed=next_stop
            produced=int(np.count_nonzero(
                np.asarray(mission_components.instrument_data_rec.baudRate,dtype=float)>0))
            energy=float(power_components.battery_rec.storageLevel[-1])/3600.0
            switched,allow=supervisor.update(elapsed,produced,energy,guard_wh=reserve_guard)
            if switched:
                upcoming=multi_targets[supervisor.active_index]
                target.specifyLocation(
                    math.radians(float(upcoming["latitude_deg"])),
                    math.radians(float(upcoming["longitude_deg"])),
                    float(upcoming["altitude_m"]),
                )
                mission_components.instrument.nodeDataName=str(upcoming["id"])
                if viz is not None:
                    vizSupport.targetLineList[0].toBodyName=str(upcoming["name"])
                    vizSupport.updateTargetLineList(viz)
                print(f"PHYSICAL RETARGET {elapsed:.1f}s -> {upcoming['id']}",flush=True)
            # Controller's attitude/access gates remain Basilisk; the supervisor
            # inhibits NEW products below the reserve, not their attitude physics.
            mission_components.controller.imaged=int(supervisor.finished_capturing or not allow)
            mission_components.transmitter.nodeBaudRate=nominal_tx if allow else 0.0
        multi_events=supervisor.events
        if len(sample_target_ids)!=len(access_rec.times()):
            raise RuntimeError("Target labels and spacecraft records have different length")
    else:
        sim.ConfigureStopTime(macros.sec2nano(plan.horizon_s))
        sim.ExecuteSimulation()

    times=np.asarray(access_rec.times(),dtype=np.float64)*1e-9
    rs=np.asarray(sc_rec.r_BN_N,dtype=np.float64)
    rg=np.asarray(ground_rec.r_LN_N,dtype=np.float64)
    elev=np.asarray(access_rec.elevation,dtype=np.float64)
    ranges=np.asarray(access_rec.slantRange,dtype=np.float64)
    access=np.asarray(access_rec.hasAccess,dtype=np.int64).astype(bool)
    if len(times)<2 or rs.shape!=(len(times),3) or rg.shape!=rs.shape:
        raise RuntimeError("Basilisk recorders yielded inconsistent dimensions")
    if not np.all(np.isfinite(rs)) or not np.all(np.isfinite(rg)):
        raise RuntimeError("Nonfinite orbit or ground coordinates")
    if not np.all(np.diff(times)>0):
        raise RuntimeError("Recorded samples must have increasing times")
    if not np.all(np.isfinite(elev)) or not np.all(np.isfinite(ranges)):
        raise RuntimeError("Nonfinite elevation or range data")

    expected=np.array([elevation_from_inertial(tuple(a),tuple(b))
                       for a,b in zip(rs,rg)])
    max_el_error_rad=float(np.max(np.abs(elev-expected)))

    # Independent rotation check uses the FIRST recorded ground position
    # to avoid asserting a physical UTC/Greenwich epoch. Checks the change
    # in inertial position against Earth spin omega, not its absolute angle.
    if sample_target_ids is None:
        rotation_expected=np.asarray([
            rotate_z(tuple(rg[0]),omega*(t-times[0])) for t in times
        ])
    else:
        rotation_expected=np.zeros_like(rg)
        ids=np.asarray(sample_target_ids)
        for label in dict.fromkeys(sample_target_ids):
            indices=np.flatnonzero(ids==label)
            first=int(indices[0])
            rotation_expected[indices]=np.asarray([
                rotate_z(tuple(rg[first]),omega*(times[i]-times[first]))
                for i in indices
            ])
    max_rotation_difference_m=float(np.max(np.linalg.norm(rg-rotation_expected,axis=1)))
    alt_ground=float(tcfg["altitude_m"])
    ground_radii=np.linalg.norm(rg,axis=1)
    max_radius_difference_m=float(
        np.max(np.abs(ground_radii-(radius+alt_ground))))
    expected_access=expected>=min_elevation
    robust=(np.abs(expected-min_elevation)>1e-6)
    visibility_mismatch=int(np.sum(access[robust]!=expected_access[robust]))

    windows=access_windows(times.tolist(),access.tolist())
    adcs_evidence = None
    if adcs_components is not None:
        if args.actuator == "rw":
            from experiments.adcs_02.analysis import analyse_run
        else:
            from experiments.adcs_01.analysis import analyse_run
        guidance_rec = adcs_components.guidance_recorder
        torque_rec = adcs_components.torque_recorder
        nav_rec = adcs_components.nav_recorder

        # Ground, physical attitude, guidance and torque are all generated at
        # the same dynamics cadence. Reject any unaligned recorder histories.
        for record in (guidance_rec, torque_rec, nav_rec):
            tt = np.asarray(record.times(), dtype=float) * 1e-9
            if tt.shape != times.shape or not np.allclose(tt, times, rtol=0, atol=1e-9):
                raise RuntimeError("ADCS guidance/torque recorder is out of sync with physical states")
        adcs_evidence = analyse_run(
            time_s=times,
            position_N_m=rs,
            target_N_m=rg,
            sigma_BN=np.asarray(sc_rec.sigma_BN, dtype=float),
            guidance_sigma_BR=np.asarray(guidance_rec.sigma_BR, dtype=float),
            guidance_omega_BR_B=np.asarray(guidance_rec.omega_BR_B, dtype=float),
            torque_Nm=np.asarray(torque_rec.torqueRequestBody, dtype=float),
            has_access=access,
            config=adcs_components.config,
            output=output,
        )
        if args.actuator == "rw":
            rw_rec = adcs_components.rw_recorder
            rw_times = np.asarray(rw_rec.times(), dtype=float) * 1e-9
            rw_speed = np.asarray(rw_rec.wheelSpeeds, dtype=float)[:, :3]
            if (rw_speed.shape != (len(times), 3) or
                    not np.allclose(rw_times, times, rtol=0, atol=1e-9) or
                    not np.all(np.isfinite(rw_speed))):
                raise RuntimeError("ADCS02 physical reaction wheel logs are not synchronized")
            rw_rpm = rw_speed / macros.RPM
            limit = float(adcs_components.config["rw"]["max_speed_rpm"])
            max_rpm = float(np.max(np.abs(rw_rpm)))
            if max_rpm > limit + 3.0:
                raise AssertionError(f"Reaction wheel physical speed limit exceeded: {max_rpm} > {limit}")
            with (output / "adcs02_reaction_wheels.csv").open(
                    "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["time_s", "wheel_1_rpm", "wheel_2_rpm", "wheel_3_rpm"])
                for ti, data in zip(times, rw_rpm):
                    writer.writerow([float(ti), *map(float, data)])
            adcs_evidence["actual_max_abs_rw_speed_rpm"] = max_rpm
            adcs_evidence["rw_speed_limit_rpm"] = limit
            adcs_evidence["rw_motor_torque_limit_nm"] = float(adcs_components.config["rw"]["max_torque_nm"])
            adcs_evidence["actuation"] = "physical_basilisk_reactionWheelStateEffector"
            (output / "adcs_summary.json").write_text(
                json.dumps(adcs_evidence, ensure_ascii=False, indent=2), encoding="utf-8")

        print(
            "ADCS pointing: initial boresight error "
            f"{adcs_evidence['initial_boresight_error_deg']:.3f} deg; "
            f"minimum {adcs_evidence['minimum_boresight_error_deg']:.3f} deg; "
            f"ready during access {adcs_evidence['pointing_ready_samples_during_access']} samples",
            flush=True,
        )
    mission_evidence = None
    if mission_components is not None:
        from experiments.mission_01.accounting import analyse_run as analyse_mission
        mission_recorder_set = (
            mission_components.station_access_rec,
            mission_components.station_ground_rec,
            mission_components.capture_command_rec,
            mission_components.instrument_data_rec,
            mission_components.storage_rec,
            mission_components.transmitter_rec,
        )
        for recorder in mission_recorder_set:
            tt = np.asarray(recorder.times(), dtype=float) * 1e-9
            if tt.shape != times.shape or not np.allclose(tt, times, rtol=0, atol=1e-9):
                raise RuntimeError("Mission 01 recorders are not synchronous with the physical spacecraft")
        mission_evidence = analyse_mission(
            times=times, sc_r_N=rs, target_r_N=rg,
            station_r_N=np.asarray(mission_components.station_ground_rec.r_LN_N, dtype=float),
            sigma_BN=np.asarray(sc_rec.sigma_BN, dtype=float),
            target_access=access,
            station_access=np.asarray(mission_components.station_access_rec.hasAccess, dtype=bool),
            command=np.asarray(mission_components.capture_command_rec.deviceCmd, dtype=int),
            instrument_baud=np.asarray(mission_components.instrument_data_rec.baudRate, dtype=float),
            transmitter_baud=np.asarray(mission_components.transmitter_rec.baudRate, dtype=float),
            storage_bits=np.asarray(mission_components.storage_rec.storageLevel, dtype=float),
            adcs_guid_sigma=np.asarray(adcs_components.guidance_recorder.sigma_BR, dtype=float),
            adcs_guid_rate=np.asarray(adcs_components.guidance_recorder.omega_BR_B, dtype=float),
            boresight_B=adcs_components.config["instrument_boresight_B"],
            config=mission_components.config, output=output
        )
        print(
            "Mission 01: captured at "
            f"{mission_evidence['capture_time_s']:.1f} s, generated "
            f"{mission_evidence['generated_bits']/8e6:.3f} MB, downlinked "
            f"{mission_evidence['downlinked_bits']/8e6:.3f} MB, "
            f"remaining {mission_evidence['final_stored_bits']/8e6:.3f} MB",
            flush=True,
        )
    power_evidence = None
    if power_components is not None:
        from experiments.power_01.analysis import analyse_run as analyse_power
        power_evidence = analyse_power(
            times=times,
            components=power_components,
            output=output,
        )
        print("POWER 01: final battery"
              f" {power_evidence['final_battery_wh']:.3f} Wh,"
              f" generated {power_evidence['solar_energy_wh']:.3f} Wh",flush=True)

    payload_evidence = None
    if args.payload:
        from experiments.payload_01.accounting import validate_generation, save_evidence

        commands = np.asarray(payload_command_rec.deviceCmd, dtype=np.int64)
        rates = np.asarray(payload_data_rec.baudRate, dtype=np.float64)
        data_times = np.asarray(payload_data_rec.times(), dtype=np.float64) * 1e-9
        command_times = np.asarray(payload_command_rec.times(), dtype=np.float64) * 1e-9
        if not (len(commands) == len(rates) == len(times)
                and np.allclose(data_times, times, rtol=0, atol=1e-9)
                and np.allclose(command_times, times, rtol=0, atol=1e-9)):
            raise RuntimeError("Instrument time series are not synchronized with ground visibility")
        events = validate_generation(
            times.tolist(), access.tolist(), commands.tolist(),
            rates.tolist(), step, payload_cfg["bytes_per_product"] * 8
        )
        payload_folder = (
            "payload_01" if plan.output_name == "ground_01"
            else f"payload_01_{plan.output_name}"
        )
        save_evidence(ROOT / "results" / payload_folder, payload_cfg, step, events)
        payload_evidence = {
            "experiment": "Payload 01",
            "products_generated": len(events),
            "total_data_bits_generated": sum(e["product_bits"] for e in events),
            "data_destination": "none; memory and radio are not connected",
            "report": f"results/{payload_folder}/summary.json",
        }
    with (output/"access.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.writer(handle)
        writer.writerow(["time_s","sc_x_m","sc_y_m","sc_z_m",
                         "ground_x_m","ground_y_m","ground_z_m",
                         "elevation_deg","slant_range_m","has_access"])
        for t, r_sat, r_ground, el, distance, visible in zip(
            times,rs,rg,elev,ranges,access
        ):
            writer.writerow([float(t),*map(float,r_sat),
                             *map(float,r_ground),math.degrees(float(el)),
                             float(distance),int(visible)])
    draw_plots(times,np.degrees(elev),ranges/1000,access,
               float(tcfg["minimum_elevation_deg"]),output)

    summary={
        "scenario":params,
        "orbit_initial_conditions":orbit_cfg,
        "software":{"bsk":version("bsk")},
        "assumptions":[
            "Synthetic Earth-centred circular point-mass orbit",
            "Constant Earth spin with arbitrary initial sidereal angle and no UTC epoch",
            "Spherical Earth ground target, no ellipsoid or terrain",
            "Geometric access only; no camera FOV/attitude, Sun illumination or clouds",
            "Window boundaries sampled at simulation cadence, uncertainty up to one step"
        ],
        "orbit_period_s":period,
        "run_plan": plan.as_dict(),
        "requested_duration_s": plan.horizon_s,
        "last_sample_time_s": float(times[-1]),
        "physics_step_s": step,
        "earth_mu_m3_s2":mu,
        "samples":len(times),
        "access_samples":int(np.sum(access)),
        "max_elevation_deg":float(np.max(np.degrees(elev))),
        "minimum_slant_range_km":float(np.min(ranges)/1000),
        "windows":windows,
        "payload": payload_evidence,
        "adcs": adcs_evidence,
        "mission": mission_evidence,
        "actuator": args.actuator if adcs_components is not None else None,
        "power": power_evidence,
        "vizard": {
            "requested": plan.viz_mode != "off",
            "mode": plan.viz_mode,
            "visualization_step_s": plan.viz_step_s,
            "live_acceleration": plan.live_speed,
            "live_connection": (
                f"tcp://127.0.0.1:{plan.live_port}" if plan.viz_mode == "live" else None
            ),
            "status": viz_status,
            "output_file": str(viz_file) if viz_file else None,
            "file_created": bool(viz_file and viz_file.is_file()),
            "earth_attitude_source": "planetEphemeris planetOutMsgs[0] -> earth.planetBodyInMsg",
            "ground_location_source": "spherical body-fixed coordinates from config.json",
            "parent_body_name": str(earth.displayName) if plan.viz_mode != "off" else None,
            "planet_name_internal": str(earth.planetName) if plan.viz_mode != "off" else None,
            "marker_name": str(tcfg["name"]) if plan.viz_mode != "off" else None,
            "marker_color_rgba": [255, 0, 255, 255] if plan.viz_mode != "off" else None,
            "marker_scale": 15.0 if plan.viz_mode != "off" else None,
            "location_registered": bool(plan.viz_mode != "off" and str(tcfg["name"]) in viz_location_names),
        },
        "checks":{
            "max_elevation_difference_rad":max_el_error_rad,
            "max_earth_rotation_position_difference_m":max_rotation_difference_m,
            "max_ground_radius_difference_m":max_radius_difference_m,
            "access_mismatch_count_away_from_threshold":visibility_mismatch
        },
        "check_limits":{
            "max_elevation_difference_rad":1e-6,
            "max_earth_rotation_position_difference_m":1.0,
            "max_ground_radius_difference_m":1.0,
            "access_mismatch_count_away_from_threshold":0
        }
    }
    summary["checks_passed"]=all(
        summary["checks"][key]<=limit for key,limit in summary["check_limits"].items()
    )
    (output/"summary.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    input_files = {
        "ground_config": (CONF, params, ground_config_sha),
        "orbit_config": (orbit_config, orbit_cfg, orbit_config_sha),
    }
    if args.payload:
        from experiments.payload_01.integration import CONFIG as PAYLOAD_CONFIG
        input_files["payload_config"] = (PAYLOAD_CONFIG, payload_cfg, payload_config_sha)
    if adcs_components is not None:
        if args.actuator == "rw":
            from experiments.adcs_02.integration import CONFIG as ADCS_CONFIG
        else:
            from experiments.adcs_01.integration import CONFIG as ADCS_CONFIG
        input_files["adcs_config"] = (
            ADCS_CONFIG, adcs_components.config, adcs_components.config_sha256
        )
    if power_components is not None:
        from experiments.power_01.integration import CONFIG as POWER_CONFIG
        input_files["power_config"] = (
            POWER_CONFIG, power_components.config, power_components.config_sha256
        )
    if mission_components is not None:
        input_files["mission_config"] = (
            mission_components.config_path,
            mission_components.config,
            mission_components.sha256
        )
    write_run_explanation(
        output=output,
        plan=plan.as_dict(),
        configs=input_files,
        summary=summary,
        software=summary["software"],
        notes=summary["assumptions"] + [
            "All output folder names are local; previous contents of the same run name are overwritten",
            "Playback speed for a saved file is controlled inside Vizard, not by the physics integrator",
            "Live mode requires Vizard DirectComm; no stand-alone live test is performed in CI",
            "Ground 01 tracks only one target; longer windows do not imply additional real imaging",
            "Payload 01 controller captures only one synthetic product per whole run",
            ("ADCS 01 simulates rigid-body pointing but uses truth-like navigation and "
             "an unlimited ideal external control torque; no wheel hardware or real camera"
             if args.adcs or args.mission else "ADCS not connected, ideal pointing only if Payload is selected"),
            ("Mission 01 uses a fixed data product, finite bits storage and an ideal "
             "packet transmitter; not a camera optic or physical link budget"
             if args.mission else "Mission 01 data chain not connected"),
        ],
    )
    print("Ground 01 samples:",len(times))
    print("Access windows:",len(windows))
    for i, window in enumerate(windows, start=1):
        if window["duration_upper_bound_s"] is not None:
            print(
                f"Window {i} sampled: first={window['first_access_sample_s']:.0f}s, "
                f"last={window['last_access_sample_s']:.0f}s; "
                f"duration bracket=[{window['duration_lower_bound_s']:.0f}, "
                f"{window['duration_upper_bound_s']:.0f}]s"
            )
        else:
            print(f"Window {i} clipped by simulation limits; duration upper bound unknown")
    print("Max elevation:",f"{summary['max_elevation_deg']:.3f} deg")
    print("Min slant range:",f"{summary['minimum_slant_range_km']:.3f} km")
    print("Checks:",summary["checks"])
    print("Ground geometry:", "PASS" if summary["checks_passed"] else "FAIL")
    print("Vizard:", viz_status)
    if viz_file is not None:
        print(f"Vizard file: {viz_file} (exists={viz_file.is_file()})")
        if not viz_file.is_file() or viz_file.stat().st_size <= 0:
            raise RuntimeError("Vizard was requested but no non-empty playback file was written")
    print(f"Results: results/{plan.output_name}")
    print("Input provenance and definitions: run_manifest.json and RESULTS_EXPLAINED.md")
    if adcs_evidence:
        print("ADCS diagnostics: adcs_states.csv and adcs_summary.json")
    if mission_evidence:
        print("Mission data chain: mission_states.csv, mission_summary.json and mission_dataflow.png")
    if payload_evidence:
        print(
            f"Payload 01: {payload_evidence['products_generated']} synthetic product(s), "
            f"{payload_evidence['total_data_bits_generated']} bits generated; "
            "NOT stored or delivered"
        )
        print(f"Payload evidence: {payload_evidence['report']} and events.csv")
    if not summary["checks_passed"]:
        raise SystemExit("Ground 01 geometric validation failed; inspect summary.json")


if __name__=="__main__":
    main()
