"""Reproducible Mission 02 CLI.

Uses the EXISTING verified Basilisk Ground 01 to propagate the spacecraft;
then executes resource-limited mission operations on the resulting state track.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from experiments.mission_02.model import load_basilisk_track, simulate, validate

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")
POLICIES = ("fifo", "edf", "priority")


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(args):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.output_name):
        raise ValueError("--output-name must contain only A-Z, a-z, 0-9, _ and -")
    if args.duration_hours <= 0 or args.step_s <= 0:
        raise ValueError("Duration and step must be positive")
    output = ROOT / "results" / args.output_name
    if output.exists() and not args.overwrite:
        raise FileExistsError(
            f"{output} already exists: use a new --output-name or explicit --overwrite"
        )
    raw = args.config.read_bytes()
    config = json.loads(raw)
    if args.radio_bps is not None:
        config = copy.deepcopy(config)
        config["radio"]["nominal_rate_bps"] = args.radio_bps
    if args.battery_wh is not None:
        config = copy.deepcopy(config)
        config["power"]["initial_wh"] = args.battery_wh
    if args.storage_bytes is not None:
        config = copy.deepcopy(config)
        config["spacecraft"]["storage_capacity_bytes"] = args.storage_bytes
    validate(config, args.step_s)
    if args.plan_only:
        print(json.dumps({"config": config, "output": str(output),
                          "generates_orbit": args.track is None,
                          "policies": POLICIES if args.policy == "all" else [args.policy]},
                         ensure_ascii=False, indent=2))
        return

    if args.track is None:
        geom_name = args.output_name + "_basilisk_geometry"
        geo_path = ROOT / "results" / geom_name
        if geo_path.exists() and not args.overwrite:
            raise FileExistsError(
                f"{geo_path} already exists; select another --output-name or --overwrite"
            )
        command = [
            sys.executable, "-m", "experiments.ground_01.run_ground",
            "--duration-hours", str(args.duration_hours), "--step-s", str(args.step_s),
            "--viz-mode", "off", "--output-name", geom_name
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        track = geo_path / "access.csv"
    else:
        track = args.track.resolve()
        if not track.is_file():
            raise FileNotFoundError(track)

    states = load_basilisk_track(track)
    actual_step = states[1].t_s - states[0].t_s
    if abs(actual_step - args.step_s) > 1e-7:
        raise ValueError("Track step does not match --step-s")
    if args.track is not None and states[-1].t_s + actual_step < args.duration_hours * 3600:
        print("NOTE: provided track is shorter than requested duration", file=sys.stderr)
    output.mkdir(parents=True, exist_ok=True)
    (output / "configuration_used.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "model": "Mission 02 resource-limited operations, not a full ADCS/power/RF dynamics run",
        "input_config_path": str(args.config),
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "orbit_track": str(track),
        "orbit_track_sha256": hashlib.sha256(track.read_bytes()).hexdigest(),
        "command_overrides": {"radio_bps": args.radio_bps,
                              "battery_wh": args.battery_wh,
                              "storage_bytes": args.storage_bytes},
        "step_s": actual_step, "samples": len(states),
        "orbit_source": "existing Ground 01 Basilisk spacecraft outputs if not --track",
        "hardware_truth": "SYNTHETIC / UNCALIBRATED",
        "assumptions": "Read README.md before interpreting physical fidelity",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    policies = POLICIES if args.policy == "all" else (args.policy,)
    summaries = []
    for policy in policies:
        result = simulate(states, config, policy)
        report = result["summary"]
        summaries.append(report)
        (output / f"{policy}_summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / f"{policy}_events.json").write_text(
            json.dumps(result["events"], ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(output / f"{policy}_states.csv", result["trace"],
                  ["time_s", "activity", "task", "station", "storage_bits",
                   "battery_wh", "sunlit", "generated_bits", "transmitted_bits"])
    write_csv(output / "comparison.csv", summaries,
              ["policy", "tasks", "captured", "fully_delivered",
               "delivered_on_time", "weighted_on_time_fraction",
               "generated_bits", "transmitted_bits", "stored_bits",
               "max_stored_bits", "capacity_bits", "balance_error_bits",
               "final_battery_wh", "min_battery_wh", "solar_energy_wh",
               "consumed_energy_wh", "eclipse_samples", "power_limited_samples",
               "sample_step_s"])
    (output / "comparison.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    from experiments.mission_02.plots import render_summary
    rendered = render_summary(output)
    if rendered:
        print("Created figures:", ", ".join(rendered))
    print("Mission 02 finished. Open:", output)
    for summary in summaries:
        print(f"  {summary['policy']:8s} weighted_on_time={summary['weighted_on_time_fraction']:.4f}"
              f" captured={summary['captured']} delivered={summary['fully_delivered']}"
              f" generated_bits={summary['generated_bits']}"
              f" transmitted_bits={summary['transmitted_bits']}"
              f" min_battery_Wh={summary['min_battery_wh']}")


def main():
    parser = argparse.ArgumentParser(
        description="Basilisk orbit + bounded, multi-target mission scheduling")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--track", type=Path,
                        help="Existing results/.../access.csv from Basilisk Ground 01")
    parser.add_argument("--policy", choices=("all", *POLICIES), default="all")
    parser.add_argument("--duration-hours", type=float, default=4)
    parser.add_argument("--step-s", type=float, default=10)
    parser.add_argument("--radio-bps", type=float)
    parser.add_argument("--battery-wh", type=float)
    parser.add_argument("--storage-bytes", type=int)
    parser.add_argument("--output-name", default="mission02_reference")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
