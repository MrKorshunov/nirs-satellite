"""Reproducible orbit integration-step comparison: 10 s against 5 s.

Runs the same physical model twice, stores separate outputs, compares states
at identical sample times and independently checks both against the exact
two-body circular Kepler solution. Does not rewrite config.json.
"""
from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from pathlib import Path

from experiments.orbit_01.validate_orbit import validate

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
EXPERIMENT = "experiments.orbit_01.run_orbit"


def read_states(folder: Path) -> dict[int, tuple[tuple[float, ...], tuple[float, ...]]]:
    """Return {time_ns: (r_xyz_m, v_xyz_m/s)}; guards duplicate timestamps."""
    data: dict[int, tuple[tuple[float, ...], tuple[float, ...]]] = {}
    with (folder / "states.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            time_ns = round(float(row["time_s"]) * 1e9)
            if time_ns in data:
                raise ValueError("Duplicate sample time")
            r = tuple(float(row[k]) for k in ("x_m", "y_m", "z_m"))
            v = tuple(float(row[k]) for k in ("vx_m_s", "vy_m_s", "vz_m_s"))
            data[time_ns] = (r, v)
    return data


def norm_diff(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))


def compare_folders(coarse: Path, fine: Path) -> dict:
    a = read_states(coarse)
    b = read_states(fine)
    common = sorted(set(a) & set(b))
    if len(common) < 100:
        raise AssertionError("Not enough matching timestamps; inspect time grids")
    pos_errors = [norm_diff(a[t][0], b[t][0]) for t in common]
    vel_errors = [norm_diff(a[t][1], b[t][1]) for t in common]
    ca = validate(coarse)
    fa = validate(fine)
    result = {
        "method": "10s versus 5s with matched epochs and independent analytic checks",
        "coarse_step_s": 10.0,
        "fine_step_s": 5.0,
        "common_epochs": len(common),
        "maximum_position_difference_m": max(pos_errors),
        "maximum_velocity_difference_m_s": max(vel_errors),
        "coarse_analytic_max_position_error_m": ca["measured"]["max_position_error_m"],
        "fine_analytic_max_position_error_m": fa["measured"]["max_position_error_m"],
        "coarse_analytic_max_velocity_error_m_s": ca["measured"]["max_velocity_error_m_s"],
        "fine_analytic_max_velocity_error_m_s": fa["measured"]["max_velocity_error_m_s"],
        "analytic_validation_passed_both": ca["passed"] and fa["passed"],
        "limitations": [
            "Two steps alone do not demonstrate the formal convergence order",
            "The analytical reference is valid only for a point-mass circular orbit",
            "Reference uses initial state recorded by Basilisk: separate absolute initial-condition checks also required",
        ],
    }
    # Floating-point floor matters at tiny errors; avoid asserting a strict
    # 16x ratio expected of fourth-order methods in this short demonstration.
    result["fine_step_not_materially_worse"] = (
        result["fine_analytic_max_position_error_m"]
        <= max(1e-5, result["coarse_analytic_max_position_error_m"] * 1.1)
        and result["fine_analytic_max_velocity_error_m_s"]
        <= max(1e-7, result["coarse_analytic_max_velocity_error_m_s"] * 1.1)
    )
    return result


def main() -> None:
    for step, label in [(10, "orbit_01_step10"), (5, "orbit_01_step05")]:
        cmd = [
            sys.executable, "-m", EXPERIMENT,
            "--step-s", str(step), "--output-name", label,
        ]
        print(f"Calculating reference scenario with {step}-second step...", flush=True)
        subprocess.run(cmd, cwd=ROOT, check=True)
    report = compare_folders(RESULTS / "orbit_01_step10", RESULTS / "orbit_01_step05")
    output = RESULTS / "orbit_01_convergence.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Matched epochs:", report["common_epochs"])
    print(f"Max coordinate difference between runs: {report['maximum_position_difference_m']:.9g} m")
    print(f"Max velocity difference between runs: {report['maximum_velocity_difference_m_s']:.9g} m/s")
    print(f"Analytic max position error, 10 s: {report['coarse_analytic_max_position_error_m']:.9g} m")
    print(f"Analytic max position error, 5 s: {report['fine_analytic_max_position_error_m']:.9g} m")
    print("Analytic validation both:", "PASS" if report["analytic_validation_passed_both"] else "FAIL")
    print("Fine step not materially worse:", report["fine_step_not_materially_worse"])
    print("Report (relative): results/orbit_01_convergence.json")
    if not report["analytic_validation_passed_both"] or not report["fine_step_not_materially_worse"]:
        raise SystemExit("Convergence checks failed; inspect report")


if __name__ == "__main__":
    main()
