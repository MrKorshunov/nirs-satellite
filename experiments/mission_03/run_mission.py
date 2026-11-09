"""Physical multi-target satellite demonstrator with real Basilisk RW + power + datachain.

All satellite hardware numbers use inputs/physical/*.json. The two target
locations are read from inputs/physical/multitarget_demo.json.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def main()->None:
    args=sys.argv[1:]
    if not any(x=="--duration-hours" or x.startswith("--duration-hours=")
               for x in args):
        args=["--duration-hours","0.2",*args]
    if not any(x=="--output-name" or x.startswith("--output-name=")
               for x in args):
        args=["--output-name","mission03_physical",*args]
    cmd=[sys.executable,"-m","experiments.ground_01.run_ground",
         "--mission","--multi-target","--actuator","rw","--power",*args]
    completed=subprocess.run(cmd,cwd=ROOT,check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)
    print("Mission 03: physical multi-target demonstration complete")

if __name__=="__main__":
    main()
