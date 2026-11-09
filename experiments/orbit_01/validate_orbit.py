"""Independent check of the circular two-body Basilisk orbit.

Reads generated CSV and JSON, computes the analytical circular Kepler orbit
using Python's standard library (no Basilisk and no NumPy in this file).
This verifies the saved *numerical trajectory*, not just formulas for T and v.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "orbit_01"


def vector_norm(values: tuple[float, float, float]) -> float:
    return math.sqrt(sum(x * x for x in values))


def validate(results: Path = RESULTS) -> dict:
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    scenario = summary["scenario"]
    if scenario["eccentricity"] != 0:
        raise ValueError("Analytical validator only supports circular orbits")
    mu = float(summary["earth_mu_m3_s2"])
    semi_major_axis = float(summary["semi_major_axis_m"])
    omega = math.sqrt(mu / semi_major_axis**3)

    with (results / "states.csv").open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) < 3:
        raise AssertionError("Too few trajectory samples for validation")

    r0 = tuple(float(rows[0][axis]) for axis in ("x_m", "y_m", "z_m"))
    v0 = tuple(float(rows[0][axis]) for axis in ("vx_m_s", "vy_m_s", "vz_m_s"))
    initial_time_s = float(rows[0]["time_s"])

    initial_radius_error_m = abs(vector_norm(r0) - semi_major_axis)
    initial_speed_error_m_s = abs(vector_norm(v0) - math.sqrt(mu / semi_major_axis))
    initial_radial_velocity_m_s = abs(sum(r * v for r, v in zip(r0, v0)) / vector_norm(r0))

    max_position_error_m = 0.0
    max_velocity_error_m_s = 0.0
    for row in rows:
        time_s = float(row["time_s"]) - initial_time_s
        c = math.cos(omega * time_s)
        s = math.sin(omega * time_s)

        # Exact solution for the same central-force circular orbit:
        # r(t) = r0*cos(omega*t) + v0/omega*sin(omega*t)
        # v(t) = -omega*r0*sin(omega*t) + v0*cos(omega*t)
        expected_r = tuple(r * c + (v / omega) * s for r, v in zip(r0, v0))
        expected_v = tuple(-omega * r * s + v * c for r, v in zip(r0, v0))
        measured_r = tuple(float(row[axis]) for axis in ("x_m", "y_m", "z_m"))
        measured_v = tuple(float(row[axis]) for axis in ("vx_m_s", "vy_m_s", "vz_m_s"))
        max_position_error_m = max(max_position_error_m,
                                   vector_norm(tuple(a - b for a, b in zip(measured_r, expected_r))))
        max_velocity_error_m_s = max(max_velocity_error_m_s,
                                     vector_norm(tuple(a - b for a, b in zip(measured_v, expected_v))))

    # Declared tolerances are engineering acceptance criteria for this
    # controlled two-body educational case, NOT accuracy bounds for a real KA.
    tolerances = {
        "max_position_error_m": 10.0,
        "max_velocity_error_m_s": 0.02,
        "initial_radius_error_m": 0.1,
        "initial_speed_error_m_s": 0.001,
        "initial_radial_velocity_m_s": 0.001,
    }
    measured = {
        "max_position_error_m": max_position_error_m,
        "max_velocity_error_m_s": max_velocity_error_m_s,
        "initial_radius_error_m": initial_radius_error_m,
        "initial_speed_error_m_s": initial_speed_error_m_s,
        "initial_radial_velocity_m_s": initial_radial_velocity_m_s,
    }
    passed = all(value <= tolerances[name] for name, value in measured.items())
    result = {
        "method": "Independent analytical solution for circular two-body orbit",
        "samples": len(rows),
        "measured": measured,
        "tolerances": tolerances,
        "passed": passed,
        "limitations": "Valid only for circular point-mass orbit; does not validate J2, drag, epoch, or real spacecraft performance",
    }
    (results / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    report = validate()
    print(f"Reference samples: {report['samples']}")
    for name, value in report["measured"].items():
        print(f"{name}: {value:.9g} (limit: {report['tolerances'][name]})")
    print(f"Independent circular-orbit validation: {'PASS' if report['passed'] else 'FAIL'}")
    if not report["passed"]:
        raise SystemExit(1)
