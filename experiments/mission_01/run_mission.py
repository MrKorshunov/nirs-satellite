"""Run one physically integrated, yet synthetic, satellite data cycle.

Default: 12 min, physical timestep 0.5 s.
Legacy Ground/Payload/ADCS experiments are left untouched.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    arguments = sys.argv[1:]
    horizon_keys = ("--duration-hours", "--duration-days", "--orbits")
    if not any(arg in horizon_keys or any(arg.startswith(k+"=") for k in horizon_keys)
               for arg in arguments):
        arguments = ["--duration-hours", "0.2", *arguments]
    if not any(arg == "--output-name" or arg.startswith("--output-name=")
               for arg in arguments):
        arguments = ["--output-name", "mission_01", *arguments]
    result = subprocess.run(
        [sys.executable, "-m", "experiments.ground_01.run_ground",
         "--mission", *arguments],
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)
    print("Mission 01 completed. Open results/mission_01/ or your --output-name folder.")


if __name__ == "__main__":
    main()
