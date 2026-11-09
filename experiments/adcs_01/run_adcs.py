"""Run the physical Ground 01 + ADCS 01 attitude experiment.

The real dynamics/ground access remain in experiments.ground_01.run_ground.
This wrapper provides a short reproducible baseline and forwards all CLI
overrides (including --viz-mode and --plan-only).

From the repository root on Windows:
    .\\.venv\\Scripts\\python.exe -m experiments.adcs_01.run_adcs
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    arguments = sys.argv[1:]
    duration_keys = ("--duration-hours", "--duration-days", "--orbits")
    if not any(arg in duration_keys or any(arg.startswith(k+"=") for k in duration_keys)
               for arg in arguments):
        arguments = ["--duration-hours", "0.2", *arguments]
    if not any(arg == "--output-name" or arg.startswith("--output-name=")
               for arg in arguments):
        arguments = ["--output-name", "adcs_01", *arguments]
    result = subprocess.run(
        [sys.executable, "-m", "experiments.ground_01.run_ground",
         "--adcs", *arguments],
        cwd=ROOT, check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)
    print("ADCS 01 complete. See results/adcs_01/ or the --output-name folder.")


if __name__ == "__main__":
    main()
