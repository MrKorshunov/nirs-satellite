"""End-to-end Orbit->Ground->ADCS->Payload->Storage synthetic experiment."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    options = list(sys.argv[1:])
    duration = ("--duration-hours","--duration-days","--orbits")
    if not any(v in duration or any(v.startswith(k+"=") for k in duration) for v in options):
        options = ["--duration-hours","0.2",*options]
    if not any(v=="--output-name" or v.startswith("--output-name=") for v in options):
        options = ["--output-name","ground_storage01",*options]
    result = subprocess.run(
        [sys.executable,"-m","experiments.ground_01.run_ground",
         "--adcs","--payload","--storage",*options],cwd=ROOT,
    )
    if result.returncode:
        raise SystemExit(result.returncode)
    print("Storage 01 complete: results/storage_01_ground_storage01/summary.json")


if __name__=="__main__":
    main()
