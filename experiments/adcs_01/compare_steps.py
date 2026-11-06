"""Compare closed-loop ADCS at 0.5 s and 0.25 s dynamics cadences.

This is an empirical sample-rate sensitivity test, NOT a proof of the formal
integration order of Basilisk's spacecraft dynamics or any flight qualification.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"


def _records(folder: Path) -> dict[int, dict]:
    with (folder / "adcs_states.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return {round(float(row["time_s"])*1e6): row for row in rows}


def compare(coarse: Path, fine: Path) -> dict:
    a, b = _records(coarse), _records(fine)
    shared = sorted(a.keys() & b.keys())
    if len(shared) < 100:
        raise AssertionError("Too few common simulation epochs")
    errors = [
        abs(float(a[k]["boresight_error_deg"])-float(b[k]["boresight_error_deg"]))
        for k in shared
    ]
    worst = max(range(len(shared)), key=lambda i: errors[i])
    after_30s = [delta for key, delta in zip(shared, errors) if key >= 30_000_000]
    after_60s = [delta for key, delta in zip(shared, errors) if key >= 60_000_000]
    during_access = [delta for key,delta in zip(shared,errors)
                     if bool(int(a[key]["has_ground_access"]))]
    a_report = json.loads((coarse / "adcs_summary.json").read_text(encoding="utf-8"))
    b_report = json.loads((fine / "adcs_summary.json").read_text(encoding="utf-8"))
    if not a_report["checks_passed"] or not b_report["checks_passed"]:
        raise AssertionError("ADCS diagnostics failed before comparing sample steps")
    report = {
        "method": "ADCS closed-loop response 0.5s vs 0.25s, matched epochs",
        "coarse_step_s": 0.5,
        "fine_step_s": 0.25,
        "common_sample_times": len(shared),
        "max_boresight_difference_deg": max(errors),
        "mean_boresight_difference_deg": sum(errors)/len(errors),
        "worst_difference_time_s": shared[worst] / 1e6,
        "max_difference_after_30s_deg": max(after_30s),
        "max_difference_after_60s_deg": max(after_60s),
        "max_difference_during_access_deg": max(during_access) if during_access else None,
        "count_difference_above_2deg": sum(v > 2 for v in errors),
        "coarse_minimum_error_deg": a_report["minimum_boresight_error_deg"],
        "fine_minimum_error_deg": b_report["minimum_boresight_error_deg"],
        "coarse_ready_samples": a_report["pointing_ready_samples_during_access"],
        "fine_ready_samples": b_report["pointing_ready_samples_during_access"],
        "coarse_max_torque_Nm": a_report["max_commanded_torque_Nm"],
        "fine_max_torque_Nm": b_report["max_commanded_torque_Nm"],
        "limitations": [
            "Changes not just spacecraft dynamics step, but also the discrete control evaluation frequency",
            "Cannot establish formal numerical order from these two controller sampling rates",
            "Controller and actuator are idealized; Earth is spherical and orbit is two-body",
        ],
    }
    return report


def main() -> None:
    jobs = [(0.5, "adcs_01_step05"), (0.25, "adcs_01_step025")]
    for dt, name in jobs:
        print(f"Running closed-loop ADCS with step {dt:g} s", flush=True)
        subprocess.run([
            sys.executable, "-m", "experiments.adcs_01.run_adcs",
            "--step-s", str(dt), "--output-name", name,
        ], cwd=ROOT, check=True)
    r = compare(*(RESULTS / name for _,name in jobs))
    result_path = RESULTS / "adcs_01_step_comparison.json"
    result_path.write_text(json.dumps(r, indent=2), encoding="utf-8")
    print(f"Max boresight difference: {r['max_boresight_difference_deg']:.9g} deg")
    print(f"Mean boresight difference: {r['mean_boresight_difference_deg']:.9g} deg")
    print(f"Worst time: {r['worst_difference_time_s']:.6f} s")
    print(f"Max after 30s: {r['max_difference_after_30s_deg']:.9g} deg")
    print(f"Max after 60s: {r['max_difference_after_60s_deg']:.9g} deg")
    print(f"Max during actual geometric access: {r['max_difference_during_access_deg']!s} deg")
    print(f"Samples >2 deg: {r['count_difference_above_2deg']}")
    print("Report:", result_path)
    # Explicit engineering screening limit for this controlled model only,
    # not a tolerance on the pointing accuracy of any flight spacecraft.
    if not math.isfinite(r["max_boresight_difference_deg"]) or r["max_boresight_difference_deg"] > 2.0:
        raise SystemExit("ADCS sample-rate sensitivity exceeds synthetic 2-degree screening limit")


if __name__ == "__main__":
    main()
