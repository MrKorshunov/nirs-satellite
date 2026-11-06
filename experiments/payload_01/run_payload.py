"""Run Payload 01 using the existing Ground 01 physics, without code duplication.

Usage from repository root:
    .venv\\Scripts\\python.exe -m experiments.payload_01.run_payload
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    subprocess.run(
        [sys.executable, "-m", "experiments.ground_01.run_ground", "--payload"],
        cwd=ROOT,
        check=True,
    )
    print("Payload 01 experiment finished; examine results/payload_01/events.csv")


if __name__ == "__main__":
    main()
