"""Mission 03 input checks and power-command policy; no Basilisk imports.

Two declared targets are executed sequentially by a physical spacecraft.
This is a DETERMINISTIC demonstration of the execution layer, not an optimizer.
"""
from __future__ import annotations

import math

def validate(cfg: dict, *, step_s: float, product_name: str,
             partition_name: str, product_bytes: int, storage_bytes: int,
             initial_energy_wh: float) -> None:
    if not str(cfg.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("Mission 03 inputs must be marked SYNTHETIC")
    if not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("Invalid physical step")
    cadence = float(cfg["control_step_s"])
    if not math.isfinite(cadence) or cadence < step_s:
        raise ValueError("Mission control cadence must not be shorter than physical step")
    ratio = cadence / step_s
    if not math.isclose(ratio, round(ratio), abs_tol=1e-9):
        raise ValueError("Mission control cadence must be an integer multiple of physical step")
    targets = cfg["tasks"]
    if len(targets) != 2:
        raise ValueError("Mission 03 physical benchmark requires exactly TWO sequential targets")
    ids = [t["id"] for t in targets]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not i.isascii() or not i for i in ids):
        raise ValueError("Distinct nonempty ASCII target IDs required")
    if ids[0] != product_name or ids[0] != partition_name:
        raise ValueError("First target must match physical instrument and storage partition name")
    if any(len(i) > 32 for i in ids):
        raise ValueError("Target ID too long for Basilisk storage partition")
    if product_bytes <= 0 or storage_bytes < 2 * product_bytes:
        raise ValueError("Physical memory must store at least two products for this demonstration")
    if not math.isfinite(initial_energy_wh) or initial_energy_wh <= 0:
        raise ValueError("Battery must have positive initial energy")
    reserve = float(cfg["reserve_wh"])
    guard = float(cfg["reserve_guard_wh"])
    hysteresis = float(cfg["battery_reenable_hysteresis_wh"])
    if not 0 < reserve < initial_energy_wh or guard <= 0 or hysteresis <= 0:
        raise ValueError("Reserve/guard/hysteresis must be positive and below initial charge")
    # A deliberately low initial charge is a valid SAFE-MODE experiment:
    # operations must be disabled rather than rejecting the configuration.
    if all(abs(float(targets[0][k])-float(targets[1][k])) < 1e-9 for k in ("lat_deg", "lon_deg")):
        raise ValueError("Two separate target positions are necessary for actual retargeting")
    for task in targets:
        if not -90 <= float(task["lat_deg"]) <= 90:
            raise ValueError("Target latitude outside [-90, 90]")
        if not -180 <= float(task["lon_deg"]) <= 180:
            raise ValueError("Target longitude outside [-180, 180]")
        if not 0 <= float(task["minimum_elevation_deg"]) < 90:
            raise ValueError("Minimum target elevation invalid")
        if not 0 < float(task["deadline_s"]):
            raise ValueError("Invalid task deadline")
        if float(task["altitude_m"]) < 0:
            raise ValueError("Target height must be nonnegative")


def permitted(energy_wh: float, *, reserve_wh: float, guard_wh: float,
              hysteresis_wh: float, previously_permitted: bool) -> bool:
    """Hysteretic sample-and-hold battery gating, from actual Basilisk telemetry.

    The reserve is a controller threshold, not an absolute guarantee that
    an always-on bus will never subsequently drain energy in a long eclipse.
    """
    for x in (energy_wh, reserve_wh, guard_wh, hysteresis_wh):
        if not math.isfinite(x):
            raise ValueError("Nonfinite battery command parameter")
    threshold = reserve_wh + guard_wh
    if previously_permitted:
        return energy_wh >= threshold
    return energy_wh >= threshold + hysteresis_wh


def stage_for_sample(time_s: float, switch_time_s: float | None,
                     physical_step_s: float) -> int:
    """The switch occurs AFTER recording the sample at the segment boundary."""
    if switch_time_s is None:
        return 0
    return 1 if time_s > switch_time_s + physical_step_s * 0.25 else 0
