"""Input provenance and definitions of reported observables.

These are explanatory metadata, not a calibration or physical validation.
"""
from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

METRICS = {
    "samples": ("count", "Recorded time samples, not spacecraft revolutions", "len(recorded time)"),
    "access_samples": ("count", "Samples passing the geometric elevation/range test", "sum(hasAccess)"),
    "max_elevation_deg": ("deg", "Largest ground elevation angle", "max(degrees(access.elevation))"),
    "minimum_slant_range_km": ("km", "Closest geometric distance, including when Earth obstructs view", "min(access.slantRange) / 1000"),
    "windows": ("s", "Sampled geometric-access intervals; boundaries are bracketed, not exact", "Consecutive positive hasAccess flags and their neighbours"),
    "checks": ("multiple", "Consistency checks for synthetic geometry", "Independent coordinate and spin calculations"),
    "payload": ("bits, count", "Synthetic data generated, not stored or delivered", "Basilisk instrument messages plus independent accounting"),
}


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, check=True, text=True, timeout=3,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build_manifest(scenario: dict, orbit: dict, run: dict,
                   earth_mu: float, basilisk_version: str) -> dict:
    values = []

    def add(name, value, unit, origin, source, meaning):
        values.append({
            "parameter": name, "value": value, "unit": unit,
            "origin": origin, "source": source, "meaning": meaning,
        })

    ground_source = "experiments/ground_01/config.json"
    orbit_source = "experiments/orbit_01/config.json"
    for key, unit, meaning in [
        ("latitude_deg", "deg", "Geocentric latitude of the ground point"),
        ("longitude_deg", "deg", "East longitude of the ground point"),
        ("altitude_m", "m", "Ground point height above spherical Earth"),
        ("minimum_elevation_deg", "deg", "Geometric access elevation threshold"),
        ("maximum_range_m", "m", "Optional maximum access range; -1 means disabled"),
    ]:
        add("target."+key, scenario["target"][key], unit, "synthetic", ground_source, meaning)
    for key, unit, meaning in [
        ("rotation_rate_rad_s", "rad/s", "Constant Earth rotation speed"),
        ("initial_sidereal_angle_deg", "deg", "Synthetic Earth orientation without UTC"),
        ("rotational_pole_ra_deg", "deg", "Synthetic spin-axis right ascension"),
        ("rotational_pole_dec_deg", "deg", "Synthetic spin-axis declination"),
    ]:
        add("earth."+key, scenario["earth"][key], unit, "assumed_model", ground_source, meaning)
    for key, unit, meaning in [
        ("reference_radius_m", "m", "Reference radius, WGS84 equatorial value used as a sphere"),
        ("initial_altitude_m", "m", "Chosen orbital height"),
        ("inclination_deg", "deg", "Orbital inclination"),
        ("raan_deg", "deg", "Orbital right ascension of ascending node"),
        ("eccentricity", "1", "Initial eccentricity"),
        ("hub_mass_kg", "kg", "Synthetic hub mass for simulator initialization"),
        ("hub_inertia_diag_kg_m2", "kg m^2", "Synthetic hub inertia moments"),
    ]:
        add("orbit."+key, orbit[key], unit, "synthetic", orbit_source, meaning)
    for key, unit, meaning in [
        ("duration_s", "s", "Requested model-time horizon"),
        ("physics_step_s", "s", "Numerical dynamics and ground-access update period"),
        ("record_step_s", "s", "Saved CSV/plot sample period"),
        ("viz_step_s", "s", "Vizard frame interval; null for batch mode"),
        ("live_speed_factor", "model s / wall s", "Live synchronization factor"),
    ]:
        add("run."+key, run[key], unit, "user_setting",
            "CLI override or experiments/ground_01/config.json", meaning)
    add("earth.mu", earth_mu, "m^3/s^2", "library_constant",
        "Basilisk gravBodyFactory.createEarth().mu (pinned package version)",
        "Gravitational parameter used by point-mass propagator")
    return {
        "purpose": "Synthetic Ground 01 research experiment",
        "origin_policy": "SYNTHETIC does not mean measured or validated",
        "software": {
            "bsk": basilisk_version,
            "python": platform.python_version(),
            "platform": platform.system(),
            "git_commit": git_commit(),
        },
        "run": run,
        "parameters": values,
        "metrics": {name: {
            "unit": unit, "meaning": meaning, "calculation": calculation
        } for name, (unit, meaning, calculation) in METRICS.items()},
        "limitations": [
            "Synthetic Earth and satellite with no real UTC epoch",
            "Two-body point-mass orbital dynamics; no atmospheric drag or J2",
            "No realistic attitude, camera optics, spacecraft power or communication link",
            "Payload 01 allows only one synthetic product for one orbit",
        ],
    }


def save_metadata(output: Path, manifest: dict, summary: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "inputs_and_metrics.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run = manifest["run"]
    lines = [
        "# Explanation of Ground 01 results",
        "",
        "## Run settings",
        "",
        f"- Requested model time: {run['duration_s']/3600:.3f} hours ({run['duration_source']})",
        f"- Physics step: {run['physics_step_s']} seconds",
        f"- Saved-data step: {run['record_step_s']} seconds",
        f"- Vizard frame step: {run['viz_step_s']} seconds",
        f"- Mode: {run['mode']}, live speed factor: {run['live_speed_factor']}",
        f"- Number of recorded states: {summary['samples']}",
        f"- Last recorded model time: {summary['last_recorded_time_s']:.2f} seconds",
        "",
        "## Main results",
        "",
        f"- Geometric access samples: {summary['access_samples']}",
        f"- Geometric access windows: {len(summary['windows'])}",
        f"- Peak elevation angle: {summary['max_elevation_deg']:.5f} degrees",
        f"- Minimum geometric slant range: {summary['minimum_slant_range_km']:.5f} km",
        f"- Geometric consistency checks: {'PASS' if summary['checks_passed'] else 'FAIL'}",
        "",
        "## What each result means and where it came from",
        "",
    ]
    for name, (unit, meaning, calculation) in METRICS.items():
        lines.extend([f"### {name} ({unit})", meaning, "",
                      f"Calculation: {calculation}", ""])
    lines.extend([
        "## Important limitations",
        "",
        "All satellite, target and epoch settings are synthetic or assumed.",
        "These outputs are NOT observations or telemetry from a real satellite.",
        "A Vizard animation and a successful numerical test do not validate real flight dynamics.",
        "",
        "Resolved inputs and their origins are in inputs_and_metrics.json.",
    ])
    (output / "EXPLAIN_RESULTS.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
