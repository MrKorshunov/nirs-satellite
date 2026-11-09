"""Pure standard-library checks of all synthetic mission parameters.

This module intentionally does not import Basilisk or numpy; it runs in CI
before the scientific simulator and rejects incompatible configurations.
"""
from __future__ import annotations

import math

def validate_config(config: dict, step_s: float) -> None:
    if not str(config.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("Mission inputs must identify the synthetic nature of data")
    capture, storage, downlink = (
        config["capture"], config["storage"], config["downlink"]
    )
    def pos_int(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value
    bits = 8 * pos_int(capture["product_bytes"], "product_bytes")
    capacity_bits = 8 * pos_int(storage["capacity_bytes"], "capacity_bytes")
    packet_bits = 8 * pos_int(downlink["packet_bytes"], "packet_bytes")
    if not isinstance(capture["maximum_products_per_run"], int) or capture["maximum_products_per_run"] != 1:
        raise ValueError("Mission 01 currently supports only ONE synthetic product per whole run")
    if storage["initial_bytes"] != 0 or capacity_bits < bits:
        raise ValueError("Mission 01 needs empty storage large enough for its single product")
    if packet_bits > bits or bits % packet_bits:
        raise ValueError("Packet size must divide product size for traceable accounting")
    if not 0 < float(config["capture"]["maximum_attitude_mrp_error"]) < 1:
        raise ValueError("Invalid dimensionless MRP tolerance")
    if not 0 < float(capture["maximum_rate_error_rad_s"]) < 1:
        raise ValueError("Invalid attitude rate tolerance")
    if not math.isclose(float(capture["assumed_exposure_duration_s"]), step_s,
                        rel_tol=0, abs_tol=1e-12):
        raise ValueError("This first-order instrument assumes one product per physical time step")
    if not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("Invalid step_s")
    rate = float(downlink["rate_bits_per_s"])
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Radio rate must be positive and finite")
    station = downlink["ground_station"]
    latitude, longitude, elevation = (
        float(station["latitude_deg"]), float(station["longitude_deg"]),
        float(station["minimum_elevation_deg"])
    )
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180
            and 0 <= elevation < 90 and float(station["altitude_m"]) >= 0):
        raise ValueError("Invalid synthetic station coordinates or mask")
    if not str(storage["partition_name"]) == str(capture["product_name"]):
        raise ValueError("Storage partition must match instrument data name")
    if len(str(capture["product_name"])) >= 100:
        raise ValueError("Short data partition name required")


