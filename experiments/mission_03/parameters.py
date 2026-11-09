"""Independent validation of the Mission03 command plan and common hardware.

This module intentionally has no Basilisk, numpy or matplotlib dependencies.
"""
from __future__ import annotations
import math

def validate(cfg:dict, hardware:dict, step:float)->None:
    if not str(cfg.get("provenance","")).startswith("SYNTHETIC"):
        raise ValueError("Physical multi-target plan must declare SYNTHETIC provenance")
    jobs=cfg.get("targets",[])
    if not 2<=len(jobs)<=8 or len(jobs)!=cfg.get("max_products"):
        raise ValueError("Select between 2 and 8 distinct physical targets")
    if not 0<step<=1 or not math.isfinite(step):
        raise ValueError("Physical integration step must be (0, 1] seconds")
    interval=float(cfg["command_interval_s"])
    if not math.isfinite(interval) or interval<step or not math.isclose(interval/step,round(interval/step),abs_tol=1e-9):
        raise ValueError("Command interval must be integer number of physical steps")
    reserve=float(cfg["energy_reserve_wh"])
    if not math.isfinite(reserve) or reserve<0:
        raise ValueError("Energy reserve must not be negative")
    if reserve >= float(hardware["power"]["battery_initial_wh"]):
        raise ValueError("Energy reserve must be below initial state of charge")
    if reserve >= float(hardware["power"]["battery_capacity_wh"]):
        raise ValueError("Energy reserve must be smaller than battery capacity")
    ids=[s["id"] for s in jobs]
    names=[s["name"] for s in jobs]
    if len(set(ids))!=len(ids) or len(set(names))!=len(names):
        raise ValueError("Unique partition IDs and location names required")
    mem=int(hardware["mission"]["storage"]["capacity_bytes"])
    packet=int(hardware["mission"]["downlink"]["packet_bytes"])
    if sum(int(j["product_bytes"]) for j in jobs)>mem:
        raise ValueError("Reference physical test reserves enough memory for every product")
    for job in jobs:
        for k in ("latitude_deg","longitude_deg","altitude_m","minimum_elevation_deg"):
            if not math.isfinite(float(job[k])):
                raise ValueError(f"Non-finite {k}")
        if not -90<=job["latitude_deg"]<=90 or not -180<=job["longitude_deg"]<=180:
            raise ValueError("Invalid ground target coordinates")
        if job["altitude_m"]<0 or not 0<=job["minimum_elevation_deg"]<90:
            raise ValueError("Invalid ground target altitude or elevation")
        bits=int(job["product_bytes"])
        if bits<=0 or bits%packet!=0:
            raise ValueError("Product must be positive whole number of transmitter packets")
        if not job["id"].isascii() or len(job["id"])>64:
            raise ValueError("Partition ID must be short ASCII")
    if any(abs(float(t["minimum_elevation_deg"])-float(jobs[0]["minimum_elevation_deg"]))>1e-8 for t in jobs):
        raise ValueError("All demonstrator targets currently share one minimum elevation")
