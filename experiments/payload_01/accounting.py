"""Pure Python cross-checks for Basilisk payload-generated data (SI units).

These checks are independent from Basilisk. One event represents data produced
over a simulation step: an instrument's baudRate (bits/s) times step duration.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


def validate_generation(
    times_s: list[float],
    has_access: list[bool],
    commands: list[int],
    baud_rates_bits_per_s: list[float],
    step_s: float,
    expected_bits: int,
) -> list[dict]:
    if not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("step_s must be positive and finite")
    if not isinstance(expected_bits, int) or expected_bits <= 0:
        raise ValueError("expected_bits must be a positive integer")
    if not (len(times_s) == len(has_access) == len(commands) ==
            len(baud_rates_bits_per_s)):
        raise ValueError("All time series must have identical lengths")
    if len(times_s) < 2 or any(b <= a for a, b in zip(times_s, times_s[1:])):
        raise ValueError("Expected at least two strictly increasing times")
    if any(not math.isfinite(v) for v in times_s + baud_rates_bits_per_s):
        raise ValueError("Non-finite input")
    if any(cmd not in (0, 1) for cmd in commands):
        raise ValueError("Only off/on device commands are supported")
    if any(rate < 0 for rate in baud_rates_bits_per_s):
        raise ValueError("Negative data generation rate")

    events: list[dict] = []
    for i, (t, accessible, command, rate) in enumerate(
        zip(times_s, has_access, commands, baud_rates_bits_per_s)
    ):
        if bool(command) != bool(rate > 0):
            raise AssertionError(f"Command and actual instrument rate disagree at t={t}")
        if command and not accessible:
            raise AssertionError(f"Instrument was on outside the visibility window at t={t}")
        if command:
            bits = rate * step_s
            if not math.isclose(bits, expected_bits, rel_tol=0, abs_tol=0.5):
                raise AssertionError(f"Unexpected volume at t={t}: {bits} bits")
            events.append({
                "event": "SYNTHETIC_IMAGE_DATA_GENERATED",
                "start_time_s": float(t),
                "end_time_s": float(t + step_s),
                "product_bits": int(round(bits)),
                "product_bytes": int(round(bits)) // 8,
                "source_access": True,
                "ideal_pointing": True,
            })
    if len(events) != 1:
        raise AssertionError(f"Expected exactly one product, got {len(events)}")
    return events


def save_evidence(output: Path, config: dict, step_s: float, events: list[dict]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with (output / "events.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)
    summary = {
        "scenario": config,
        "product_count": len(events),
        "products": events,
        "total_data_bits_generated": sum(e["product_bits"] for e in events),
        "total_data_bytes_generated": sum(e["product_bytes"] for e in events),
        "validation": "Independent event accounting passed; checks only synthetic geometric-window capture",
        "limitations": [
            "No physical pointing/attitude simulation; zero-error guidance assumed",
            "No actual camera, image formation, spectral channels, illumination or cloud effects",
            "Data generated, NOT stored, downlinked or delivered",
            "Event end_time_s is start_time_s + simulation step, not exposure verified by optics",
            "Earth visibility uses synthetic epoch, spherical Earth and point-mass orbit",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
