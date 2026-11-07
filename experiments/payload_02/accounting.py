"""Independent event acceptance for physically gated Basilisk instrument.

Pure Python; samples are validated against actual spacecraft body attitude
(not only against guidance error messages). No spacecraft hardware or pixels.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from experiments.payload_01.accounting import validate_generation


def verify_capture(
    *,
    times_s: list[float],
    has_access: list[bool],
    commands: list[int],
    rates: list[float],
    boresight_errors_deg: list[float],
    guidance_mrp_norms: list[float],
    rate_errors_rad_s: list[float],
    step_s: float,
    bytes_per_product: int,
    max_boresight_error_deg: float,
    max_rate_error_rad_s: float,
    mrp_tolerance: float,
) -> list[dict]:
    n = len(times_s)
    for name, data in (
        ("boresight_errors_deg", boresight_errors_deg),
        ("guidance_mrp_norms", guidance_mrp_norms),
        ("rate_errors_rad_s", rate_errors_rad_s),
    ):
        if len(data) != n or any(not math.isfinite(x) or x < 0 for x in data):
            raise ValueError(f"{name} must align and be finite, nonnegative")
    if not all(math.isfinite(x) and x > 0 for x in
               (max_boresight_error_deg, max_rate_error_rad_s, mrp_tolerance)):
        raise ValueError("Invalid positive readiness thresholds")
    events = validate_generation(
        times_s, has_access, commands, rates, step_s, bytes_per_product*8
    )
    # The original validator enforces one data product and the access and
    # baud-rate invariants, but assumed ideal pointing. Physical validation
    # below explicitly *removes* that assumption.
    for event in events:
        # Basilisk writes device commands at sampled input epochs.
        t = event["start_time_s"]
        i = next((k for k, sample in enumerate(times_s)
                  if math.isclose(t, sample, rel_tol=0, abs_tol=1e-9)), None)
        if i is None:
            raise AssertionError("Capture time is not recorded in ADCS state history")
        if boresight_errors_deg[i] > max_boresight_error_deg + 1e-6:
            raise AssertionError("Capture violated actual physical boresight accuracy")
        if guidance_mrp_norms[i] > mrp_tolerance + 1e-8:
            raise AssertionError("Capture violated guidance MRP tolerance")
        if rate_errors_rad_s[i] > max_rate_error_rad_s + 1e-8:
            raise AssertionError("Capture violated rotational tracking-rate tolerance")
        event["ideal_pointing"] = False
        event["physical_adcs_guidance_used"] = True
        event["actual_boresight_error_deg"] = float(boresight_errors_deg[i])
        event["guidance_mrp_error_norm"] = float(guidance_mrp_norms[i])
        event["tracking_rate_error_rad_s"] = float(rate_errors_rad_s[i])
    return events


def save_capture(
    output: Path,
    *,
    events: list[dict],
    config: dict,
    thresholds: dict,
) -> dict:
    if not events:
        raise ValueError("The first Payload 02 scenario must generate one product")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "events.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)
    report = {
        "scenario": "Payload 02 physical ADCS gated synthetic capture",
        "source_inputs": config,
        "thresholds": thresholds,
        "product_count": len(events),
        "products": events,
        "total_data_bits_generated": sum(e["product_bits"] for e in events),
        "total_data_bytes_generated": sum(e["product_bytes"] for e in events),
        "stored_bits": 0,
        "delivered_bits": 0,
        "validations": [
            "Basilisk device-command and actual data baud rate match",
            "Basilisk geometric access was true when commanded",
            "Independent actual body boresight-to-target LOS passed",
            "Guidance MRP and tracking-rate constraints passed at command time"
        ],
        "limitations": config["limitations"],
    }
    (output / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report
