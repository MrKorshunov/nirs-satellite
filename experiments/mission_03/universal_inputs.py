"""Validate ordered physical execution programs: N point and strip tasks.

No optimization logic; future algorithms can supply an ordered JSON document
with the same task fields. All equipment parameters come from inputs/physical.
"""
from __future__ import annotations
import math,re
from experiments.mission_03.logic import permitted
from experiments.mission_03.swath_geometry import validate_regions

ID=re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")

def validate_program(cfg:dict,regions_cfg:dict,mission_cfg:dict,power_cfg:dict,step:float)->dict:
    if not str(cfg.get("provenance","")).startswith("SYNTHETIC"):
        raise ValueError("Program must be explicitly tagged SYNTHETIC")
    if cfg.get("execution_policy")!="provided_order_only":
        raise ValueError("Executor only supports externally provided fixed-order tasks, not optimization")
    tasks=cfg.get("tasks")
    if not isinstance(tasks,list) or not 1<=len(tasks)<=64:
        raise ValueError("Physical program must contain 1..64 tasks")
    if not isinstance(step,(float,int)) or not math.isfinite(step) or step<=0 or step>1:
        raise ValueError("Physical integration step must be positive <=1s")
    positive=["control_step_s","reserve_guard_wh","battery_reenable_hysteresis_wh"]
    for key in positive:
        value=float(cfg[key])
        if not math.isfinite(value) or value<=0:
            raise ValueError("Invalid "+key)
    if not math.isclose(float(cfg["control_step_s"])/step,
                        round(float(cfg["control_step_s"])/step),abs_tol=1e-8):
        raise ValueError("control_step_s must be an integer multiple of physical step")
    reserve=float(cfg["reserve_wh"])
    if not math.isfinite(reserve) or reserve<0 or reserve>=float(power_cfg["battery_capacity_wh"]):
        raise ValueError("Energy reserve out of battery capacity")
    index=validate_regions(regions_cfg)
    names=set()
    capacity=float(mission_cfg["storage"]["capacity_bytes"])
    packet=int(mission_cfg["downlink"]["packet_bytes"])
    for job in tasks:
        name=job["id"]
        if not isinstance(name,str) or not ID.fullmatch(name) or name in names:
            raise ValueError("Each task needs a unique short ASCII id")
        names.add(name)
        kind=job.get("kind","point")
        if kind not in ("point","strip"):
            raise ValueError("Task type must be point or strip")
        release=float(job.get("release_s",0))
        deadline=float(job["deadline_s"])
        if not all(math.isfinite(v) for v in [release,deadline]) or release<0 or deadline<=release:
            raise ValueError("Invalid task release/deadline")
        if kind=="point":
            for field in ("lat_deg","lon_deg","altitude_m","minimum_elevation_deg","maximum_range_m"):
                if not math.isfinite(float(job[field])):
                    raise ValueError("Nonfinite point target "+field)
            if not -90<=job["lat_deg"]<=90 or not -180<=job["lon_deg"]<=180:
                raise ValueError("Invalid point target coordinates")
            if not 0<=job["minimum_elevation_deg"]<90 or job["altitude_m"]<0:
                raise ValueError("Invalid target elevation or altitude")
            bytes_product=int(job.get("product_bytes",mission_cfg["capture"]["product_bytes"]))
            if bytes_product<=0 or bytes_product>capacity or bytes_product%packet!=0:
                raise ValueError("Point product must fit memory and be divisible by packet size")
        else:
            if job["region_id"] not in index:
                raise ValueError("Unknown strip region: "+job["region_id"])
            if job.get("look_direction")!="nadir":
                raise ValueError("First physical strip mode supports nadir only")
            fov=float(job["fov_cross_track_deg"])
            if not math.isfinite(fov) or not 0<fov<60:
                raise ValueError("Strip FOV must be 0..60 degrees")
            lines=int(job["min_samples"])
            maximum=int(job["max_samples"])
            size=int(job["sample_bytes"])
            if not 1<=lines<=maximum<=10000 or not 0<size<=capacity:
                raise ValueError("Strip line count or sample size invalid")
            if maximum*size>capacity:
                raise ValueError("One strip task could exceed physical memory even without downlink")
    return index
