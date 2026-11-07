"""Cross-check physical Basilisk storage levels against independent data event totals."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path


def verify_storage(times_s, levels_bits, capacity_bits, data_events):
    if len(times_s) < 3 or len(times_s) != len(levels_bits):
        raise ValueError("Storage and time series must be aligned")
    if not math.isfinite(capacity_bits) or capacity_bits <= 0:
        raise ValueError("Invalid capacity")
    if any(not math.isfinite(x) for x in levels_bits):
        raise ValueError("Storage contains non-finite level")
    if any(x < -0.5 or x > capacity_bits+0.5 for x in levels_bits):
        raise AssertionError("Storage capacity violation")
    if any(v-u < -0.5 for u,v in zip(levels_bits,levels_bits[1:])):
        raise AssertionError("Storage decreased despite no transmitter or eraser")
    generated = sum(e["product_bits"] for e in data_events)
    recorded = levels_bits[-1]
    if not math.isclose(recorded, generated, rel_tol=0, abs_tol=0.5):
        raise AssertionError(f"Onboard bit balance mismatch: stored {recorded}, generated {generated}")
    return {
        "recorded_samples": len(times_s),
        "storage_capacity_bits": int(capacity_bits),
        "final_storage_bits": int(round(recorded)),
        "generated_bits": int(generated),
        "delivered_bits": 0,
        "lost_bits": 0,
        "remaining_capacity_bits": int(round(capacity_bits-recorded)),
        "max_storage_bits": int(round(max(levels_bits))),
        "integrity_passed": True,
        "limitations": [
            "Only one synthetic data product and no downlink",
            "Assumes no losses/corruption/overhead; no storage endurance model",
            "Accounting is conservation for this empty-start, no-transmitter scenario",
        ],
    }


def save(output: Path, times_s, levels_bits, report, config):
    output.mkdir(parents=True, exist_ok=True)
    with (output/"storage.csv").open("w",newline="",encoding="utf-8") as file:
        writer=csv.writer(file)
        writer.writerow(["time_s","stored_bits","stored_bytes"])
        for t,b in zip(times_s, levels_bits):
            writer.writerow([float(t),float(b),float(b)/8])
    data={"scenario":config,**report}
    (output/"summary.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    return data
