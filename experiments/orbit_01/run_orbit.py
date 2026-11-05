"""Orbit experiment 01.

Uses Basilisk 2.12.2 for the numerical dynamics. Saves transparent, traceable
outputs: positions/velocities, plots, summary, optional Vizard playback file.

Launch from repository root:
    .venv\\Scripts\\python.exe -m experiments.orbit_01.run_orbit
"""
from __future__ import annotations

import csv
import json
import math
from importlib.metadata import version
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from Basilisk.simulation import spacecraft
from Basilisk.utilities import (
    SimulationBaseClass,
    macros,
    orbitalMotion,
    simIncludeGravBody,
    vizSupport,
)

from nirs_satellite.orbit.analytical import (
    circular_speed_m_s,
    orbital_period_s,
    relative_span,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("config.json")
OUTPUT = PROJECT_ROOT / "results" / "orbit_01"


def _plot_orbit(position_m: np.ndarray, earth_radius_m: float) -> None:
    fig = plt.figure(figsize=(8, 7))
    ax = fig.add_subplot(111, projection="3d")
    theta = np.linspace(0, 2 * np.pi, 48)
    phi = np.linspace(0, np.pi, 25)
    x = earth_radius_m * np.outer(np.cos(theta), np.sin(phi))
    y = earth_radius_m * np.outer(np.sin(theta), np.sin(phi))
    z = earth_radius_m * np.outer(np.ones_like(theta), np.cos(phi))
    ax.plot_surface(x / 1000, y / 1000, z / 1000, alpha=0.20)
    p = position_m / 1000
    ax.plot(p[:, 0], p[:, 1], p[:, 2], label="Calculated orbit")
    ax.scatter(*p[0], s=35, label="Start")
    limit_km = np.max(np.abs(p)) * 1.08
    ax.set(xlim=(-limit_km, limit_km), ylim=(-limit_km, limit_km),
           zlim=(-limit_km, limit_km),
           xlabel="X (km)", ylabel="Y (km)", zlabel="Z (km)")
    ax.set_box_aspect((1, 1, 1))
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUTPUT / "orbit_3d.png", dpi=150)
    plt.close(fig)


def _plot_height(times_s: np.ndarray, position_m: np.ndarray, earth_radius_m: float) -> None:
    # Radial height above a *spherical reference*, not ellipsoidal/geodetic altitude.
    radial_height_km = (np.linalg.norm(position_m, axis=1) - earth_radius_m) / 1000
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(times_s / 60, radial_height_km)
    ax.set(xlabel="Time (minutes)", ylabel="Radial height (km)",
           title="Height above spherical reference radius")
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(OUTPUT / "radial_height.png", dpi=150)
    plt.close(fig)


def main() -> None:
    params = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if params["provenance"].startswith("SYNTHETIC") is False:
        raise ValueError("The first orbit study must remain explicitly synthetic")
    if params["eccentricity"] != 0.0:
        raise ValueError("This initial experiment is restricted to a circular orbit")
    if not (0.0 < params["time_step_s"] and params["orbits_to_simulate"] > 0):
        raise ValueError("Invalid simulation duration or time step")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    simulation = SimulationBaseClass.SimBaseClass()
    process = simulation.CreateNewProcess("orbitProcess")
    task_name = "orbitTask"
    process.addTask(simulation.CreateNewTask(task_name, macros.sec2nano(params["time_step_s"])))

    sat = spacecraft.Spacecraft()
    sat.ModelTag = "NIRS-SAT-01"
    simulation.AddModelToTask(task_name, sat)

    gravity_factory = simIncludeGravBody.gravBodyFactory()
    earth = gravity_factory.createEarth()
    earth.isCentralBody = True
    gravity_factory.addBodiesTo(sat)
    mu = float(earth.mu)

    radius = float(params["reference_radius_m"])
    a = radius + float(params["initial_altitude_m"])
    if radius <= 0 or a <= radius:
        raise ValueError("Invalid reference radius or initial altitude")

    orbit = orbitalMotion.ClassicElements()
    orbit.a = a
    orbit.e = 0.0
    orbit.i = math.radians(params["inclination_deg"])
    orbit.Omega = math.radians(params["raan_deg"])
    orbit.omega = math.radians(params["argument_of_periapsis_deg"])
    orbit.f = math.radians(params["true_anomaly_deg"])
    pos0, vel0 = orbitalMotion.elem2rv(mu, orbit)
    sat.hub.r_CN_NInit = pos0
    sat.hub.v_CN_NInit = vel0

    period = orbital_period_s(a, mu)
    simulation_duration_s = period * params["orbits_to_simulate"]
    recorder = sat.scStateOutMsg.recorder()
    simulation.AddModelToTask(task_name, recorder)

    vizard_status = "not available"
    if vizSupport.vizFound:
        try:
            vizSupport.enableUnityVisualization(
                simulation, task_name, sat, saveFile=str((OUTPUT / "orbit_01").resolve())
            )
            vizard_status = "playback recording requested"
        except Exception as exc:
            vizard_status = f"could not enable Vizard export: {type(exc).__name__}: {exc}"

    simulation.InitializeSimulation()
    simulation.ConfigureStopTime(macros.sec2nano(simulation_duration_s))
    simulation.ExecuteSimulation()

    time_s = np.asarray(recorder.times(), dtype=float) * 1e-9
    position_m = np.asarray(recorder.r_BN_N, dtype=float)
    velocity_m_s = np.asarray(recorder.v_BN_N, dtype=float)
    if len(time_s) < 3 or position_m.shape != (len(time_s), 3):
        raise RuntimeError("Basilisk output is empty or has unexpected dimensions")

    distance_m = np.linalg.norm(position_m, axis=1)
    speed_m_s = np.linalg.norm(velocity_m_s, axis=1)
    specific_energy = 0.5 * speed_m_s**2 - mu / distance_m
    angular_momentum = np.linalg.norm(np.cross(position_m, velocity_m_s), axis=1)
    energy_span = relative_span(specific_energy.tolist())
    momentum_span = relative_span(angular_momentum.tolist())

    with (OUTPUT / "states.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "x_m", "y_m", "z_m", "vx_m_s", "vy_m_s", "vz_m_s",
                         "radius_m", "radial_height_m", "speed_m_s", "specific_energy_J_kg"])
        for t, r, v, dist, speed, en in zip(
            time_s, position_m, velocity_m_s, distance_m, speed_m_s, specific_energy
        ):
            writer.writerow([float(t), *[float(q) for q in r], *[float(q) for q in v],
                             float(dist), float(dist - radius), float(speed), float(en)])

    _plot_orbit(position_m, radius)
    _plot_height(time_s, position_m, radius)

    summary = {
        "scenario": params,
        "software": {"bsk": version("bsk"), "gravity_model": "Earth point mass"},
        "earth_mu_m3_s2": mu,
        "semi_major_axis_m": a,
        "theoretical_period_s": period,
        "theoretical_circular_speed_m_s": circular_speed_m_s(a, mu),
        "simulated_time_last_sample_s": float(time_s[-1]),
        "position_sample_count": int(len(time_s)),
        "minimum_radial_height_m": float(np.min(distance_m - radius)),
        "maximum_radial_height_m": float(np.max(distance_m - radius)),
        "relative_specific_energy_span": energy_span,
        "relative_angular_momentum_span": momentum_span,
        "vizard_export": vizard_status,
        "limitations": [
            "Synthetic circular orbit, not an observed spacecraft",
            "Point-mass Earth gravity, no J2, drag, Sun or Moon",
            "Radial height uses constant spherical reference radius",
            "Plots and Vizard are visualizations of computed states, not validation",
        ],
    }
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Orbit experiment complete: {len(time_s)} samples")
    print(f"Analytical period: {period / 60:.3f} min")
    print(f"Analytical circular speed: {summary['theoretical_circular_speed_m_s'] / 1000:.4f} km/s")
    print(f"Relative energy span: {energy_span:.3e}")
    print(f"Relative angular momentum span: {momentum_span:.3e}")
    print(f"Vizard: {vizard_status}")
    print(f"Results folder: {OUTPUT}")
    if vizSupport.vizFound:
        for file in (OUTPUT.parent).rglob("*_UnityViz.bin"):
            print(f"Vizard playback file: {file}")


if __name__ == "__main__":
    main()
