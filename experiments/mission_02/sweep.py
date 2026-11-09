"""Parameter sweep on ONE frozen Basilisk trajectory (no redundant orbit reruns)."""
from __future__ import annotations

from nirs_satellite.input_paths import input_path

import argparse
import copy
import csv
import hashlib
import itertools
import json
from pathlib import Path
import re

from experiments.mission_02.model import load_basilisk_track, simulate, validate

ROOT = Path(__file__).resolve().parents[2]


def parse_floats(raw, name):
    values = [float(x.strip()) for x in raw.split(",") if x.strip()]
    if not values or any(not 0 < v < float("inf") for v in values):
        raise ValueError(f"{name} must be comma-separated positive numbers")
    return values


def main():
    parser = argparse.ArgumentParser(
        description="Mission02 independent sweep: fixed Basilisk orbit, varied resources")
    parser.add_argument("--track", type=Path, required=True)
    parser.add_argument("--config", type=Path,
                        default=input_path("observation_tasks"))
    parser.add_argument("--radio-bps", default="20000,80000,160000",
                        help="Comma-separated nominal radio rates, bits/s")
    parser.add_argument("--battery-wh", default="15,40,65",
                        help="Comma-separated initial battery energies, Wh")
    parser.add_argument("--storage-bytes", default="1000000,4000000",
                        help="Comma-separated capacities, bytes")
    parser.add_argument("--output-name", default="mission02_sweep")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", args.output_name):
        parser.error("Unsafe output name")
    track = args.track.resolve()
    states = load_basilisk_track(track)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    rates = parse_floats(args.radio_bps, "radio")
    energies = parse_floats(args.battery_wh, "battery")
    capacities = parse_floats(args.storage_bytes, "storage")
    if any(v != int(v) for v in capacities):
        parser.error("Storage capacities must be whole bytes")
    folder = ROOT / "results" / args.output_name
    if folder.exists():
        parser.error("Output exists; choose a new --output-name")
    rows = []
    for rate, battery, memory in itertools.product(rates, energies, capacities):
        condition = copy.deepcopy(config)
        condition["radio"]["nominal_rate_bps"] = rate
        condition["power"]["initial_wh"] = battery
        condition["spacecraft"]["storage_capacity_bytes"] = int(memory)
        validate(condition, states[1].t_s - states[0].t_s)
        for policy in ("fifo", "edf", "priority"):
            stats = simulate(states, condition, policy)["summary"]
            rows.append({
                "radio_rate_bps": rate,
                "initial_battery_wh": battery,
                "memory_capacity_bytes": int(memory),
                "policy": policy,
                "on_time_fraction": stats["weighted_on_time_fraction"],
                "captured": stats["captured"],
                "delivered_on_time": stats["delivered_on_time"],
                "transmitted_bits": stats["transmitted_bits"],
                "stored_bits": stats["stored_bits"],
                "min_battery_wh": stats["min_battery_wh"],
                "balance_error_bits": stats["balance_error_bits"],
            })
    folder.mkdir(parents=True)
    with (folder / "sweep.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (folder / "sweep.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "manifest.json").write_text(
        json.dumps({
            "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
            "track_sha256": hashlib.sha256(track.read_bytes()).hexdigest(),
            "track_path": str(track), "policies": ["fifo", "edf", "priority"],
            "rates": rates, "battery_wh": energies, "storage_bytes": capacities,
            "simulation_kind": "resource-limited scheduler on Basilisk orbit",
            "sample_count": len(states), "experiments": len(rows)
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} policy comparisons to {folder / 'sweep.csv'}")


if __name__ == "__main__":
    main()
