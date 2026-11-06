"""Ground 01: calculate one rotating-Earth ground target access window with Basilisk.

Runs a SYNTHETIC Earth-centred, point-mass circular-orbit experiment, using
Basilisk spacecraft + planetEphemeris + groundLocation. Produces traceable
CSV/PNG/JSON and independent checks of geometry and rotation.

From repository root:
  .venv\\Scripts\\python.exe -m experiments.ground_01.run_ground
"""
from __future__ import annotations

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
CONF = Path(__file__).with_name("config.json")

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
    if args.adcs and args.payload:
        parser.error(
            "The original Payload 01 assumes perfect pointing. ADCS 01 first "
            "validates actual attitude separately; combined imaging is a later milestone."
        )
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
        step_s=(0.5 if args.adcs and args.step_s is None else args.step_s),
        viz_mode=args.viz_mode,
        legacy_viz=args.viz,
        viz_step_s=args.viz_step_s,
        speed=args.speed,
        live_port=args.live_port,
        output_name=("adcs_01" if args.adcs and args.output_name == "ground_01"
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
            "orbit": "experiments/orbit_01/config.json (synthetic)",
            "earth_and_target": "experiments/ground_01/config.json (synthetic)",
            "time_overrides": "CLI values replace horizon, step or Vizard cadence ONLY",
        },
        "accuracy_note": "Two-body circular orbit + synthetic Earth rotation, no UTC",
    }
    if args.adcs:
        from experiments.adcs_01.integration import CONFIG as ADCS_CONFIG, validate_adcs_config
        adcs_preview = json.loads(ADCS_CONFIG.read_text(encoding="utf-8"))
        validate_adcs_config(adcs_preview, plan.step_s)
        preview["input_preview"]["adcs_initial_sigma_BN_mrp"] = adcs_preview["initial_sigma_BN_mrp"]
        preview["input_preview"]["adcs_initial_omega_BN_B_rad_s"] = adcs_preview["initial_omega_BN_B_rad_s"]
        preview["input_preview"]["adcs_boresight_B"] = adcs_preview["instrument_boresight_B"]
        preview["input_preview"]["adcs_feedback_K_Nm"] = adcs_preview["feedback_gain_K_Nm"]
        preview["input_preview"]["adcs_rate_gain_P_Nm_s"] = adcs_preview["rate_gain_P_Nm_s"]
        preview["input_sources"]["adcs"] = "experiments/adcs_01/config.json (synthetic)"
        preview["accuracy_note"] += "; ideal navigation and unlimited torque (no real actuators)"
    if args.payload:
        payload_path = ROOT / "experiments" / "payload_01" / "config.json"
        payload_plan = json.loads(payload_path.read_text(encoding="utf-8"))
        preview["input_preview"]["synthetic_payload_bytes_per_product"] = payload_plan["bytes_per_product"]
        preview["input_sources"]["payload"] = "experiments/payload_01/config.json (synthetic)"
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
    print("Origin: orbit_01/config.json + ground_01/config.json; no real UTC epoch", flush=True)
    step = plan.step_s
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
    target.ModelTag=str(tcfg["name"])
    target.planetRadius=radius
    target.minimumElevation=min_elevation
    target.maximumRange=float(tcfg["maximum_range_m"])
    target.specifyLocation(latitude,longitude,float(tcfg["altitude_m"]))
    target.addSpacecraftToModel(sat.scStateOutMsg)
    target.planetInMsg.subscribeTo(eph.planetOutMsgs[0])
    sim.AddModelToTask(task,target,ModelPriority=100)

    adcs_components = None
    if args.adcs:
        from experiments.adcs_01.integration import attach as attach_adcs
        adcs_components = attach_adcs(
            sim, task, sat, target, orbit_cfg, step
        )

    sc_rec=sat.scStateOutMsg.recorder()
    ground_rec=target.currentGroundStateOutMsg.recorder()
    access_rec=target.accessOutMsgs[0].recorder()
    for recorder in (sc_rec,ground_rec,access_rec):
        sim.AddModelToTask(task,recorder,ModelPriority=0)

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
        viz = vizSupport.enableUnityVisualization(
            sim, viz_task, sat,
            saveFile=str(viz_file) if viz_file is not None else None,
            liveStream=plan.viz_mode == "live",
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
            stationName=str(tcfg["name"]),
            parentBodyName=planet_display_name,
            r_GP_P=r_ground_fixed,
            gHat_P=normal_fixed,
            label="TARGET 14N 43E",
            markerScale=15.0,
            color=[255, 0, 255, 255],
            isHidden=False,
            fieldOfView=math.radians(160.0),
            range=2_000_000.0,
        )
        # The marker and label are visual guides, NOT proof of actual imaging.
        # The target line is always drawn, including when the Earth occludes
        # the target: physical access remains defined by access.csv.
        vizSupport.createTargetLine(
            viz, toBodyName=str(tcfg["name"]),
            lineColor=[255, 0, 255, 255],
        )
        viz.settings.showLocationLabels = 1
        viz.settings.showLocationCones = -1
        viz.settings.showLocationCommLines = -1
        viz_location_names = [str(location.stationName) for location in viz.locations]
        if str(tcfg["name"]) not in viz_location_names:
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
    sim.ConfigureStopTime(macros.sec2nano(plan.horizon_s))
    print("Computing ground access with rotating Earth...",flush=True)
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
    rotation_expected=np.asarray([
        rotate_z(tuple(rg[0]),omega*(t-times[0])) for t in times
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
        print(
            "ADCS pointing: initial boresight error "
            f"{adcs_evidence['initial_boresight_error_deg']:.3f} deg; "
            f"minimum {adcs_evidence['minimum_boresight_error_deg']:.3f} deg; "
            f"ready during access {adcs_evidence['pointing_ready_samples_during_access']} samples",
            flush=True,
        )
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
        from experiments.adcs_01.integration import CONFIG as ADCS_CONFIG
        input_files["adcs_config"] = (
            ADCS_CONFIG, adcs_components.config, adcs_components.config_sha256
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
             if args.adcs else "ADCS not connected, ideal pointing only if Payload is selected"),
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
