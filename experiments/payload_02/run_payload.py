"""Payload 02: physically pointed single synthetic data product.

Starts Ground 01 with the validated ADCS loop and instrument command.
Default 12-minute experiment, 0.5-second dynamics step.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    options = list(sys.argv[1:])
    duration = ("--duration-hours", "--duration-days", "--orbits")
    if not any(v in duration or any(v.startswith(k+"=") for k in duration)
               for v in options):
        options = ["--duration-hours", "0.2", *options]
    if not any(v == "--output-name" or v.startswith("--output-name=")
               for v in options):
        options = ["--output-name", "ground_payload02", *options]
    result = subprocess.run(
        [sys.executable, "-m", "experiments.ground_01.run_ground",
         "--adcs", "--payload", *options],
        cwd=ROOT, check=False
    )
    if result.returncode:
        raise SystemExit(result.returncode)
    print("Payload 02 complete: see results/payload_02_ground_payload02/summary.json")


if __name__ == "__main__":
    main()
