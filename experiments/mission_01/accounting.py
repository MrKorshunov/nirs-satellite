"""Independent accounting of a single simulated image data cycle (bits and seconds).

Basilisk modules generate the actual time series. These checks consume the
recorded messages and independently enforce:
  genuine pointing at the instant of capture,
  ground-access-dependent downlink,
  memory bounds and final bits conservation.

No photo pixels, bit errors or hardware RF budget are simulated.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from experiments.adcs_01.kinematics import true_boresight_error_deg
from experiments.ground_01.geometry import elevation_from_inertial, access_windows


def analyse_run(
    *, times: np.ndarray, sc_r_N: np.ndarray, target_r_N: np.ndarray,
    station_r_N: np.ndarray, sigma_BN: np.ndarray,
    target_access: np.ndarray, station_access: np.ndarray,
    command: np.ndarray, instrument_baud: np.ndarray,
    transmitter_baud: np.ndarray, storage_bits: np.ndarray,
    adcs_guid_sigma: np.ndarray, adcs_guid_rate: np.ndarray,
    boresight_B: list[float], config: dict, output: Path,
) -> dict[str, Any]:
    time = np.asarray(times, dtype=float)
    n = len(time)
    scalar = (target_access, station_access, command, instrument_baud,
              transmitter_baud, storage_bits)
    vector = (sc_r_N, target_r_N, station_r_N, sigma_BN,
              adcs_guid_sigma, adcs_guid_rate)
    if n < 3 or any(np.asarray(x).shape != (n,) for x in scalar):
        raise AssertionError("Mission 01 scalar recorder dimensions differ")
    if any(np.asarray(x).shape != (n, 3) for x in vector):
        raise AssertionError("Mission 01 physical and guidance recorder dimensions differ")
    if not np.all(np.isfinite(time)) or not np.all(np.diff(time) > 0):
        raise AssertionError("Mission timestamps must be finite and strictly increasing")
    if not all(np.all(np.isfinite(x)) for x in scalar+vector):
        raise AssertionError("Non-finite mission data")
    dt = float(np.median(np.diff(time)))
    if not np.allclose(np.diff(time), dt, rtol=0, atol=1e-8):
        raise AssertionError("Mission requires a constant physical integration step")

    access = np.asarray(target_access, dtype=bool)
    station = np.asarray(station_access, dtype=bool)
    shots = np.asarray(command, dtype=int)
    generating = np.asarray(instrument_baud, dtype=float)
    sending = np.asarray(transmitter_baud, dtype=float)
    stored = np.asarray(storage_bits, dtype=float)
    cfg_cap, cfg_store, cfg_radio = (
        config["capture"], config["storage"], config["downlink"]
    )
    bits_product = float(cfg_cap["product_bytes"])*8
    capacity_bits = float(cfg_store["capacity_bytes"])*8
    if not np.all((shots == 0) | (shots == 1)):
        raise AssertionError("Invalid instrument commands")
    if not np.all((generating > 0) == (shots > 0)):
        raise AssertionError("Exposure commands and generated data disagree")
    if np.any(generating < 0) or np.any(sending > 0):
        raise AssertionError("Instrument must create; radio must consume data")
    if np.any((sending < 0) & (~station)):
        raise AssertionError("Transmission attempted with no ground station access")
    if np.any((shots > 0) & (~access)):
        raise AssertionError("Exposure attempted without target visibility")
    if np.min(stored) < -0.5 or np.max(stored) > capacity_bits+0.5:
        raise AssertionError("Storage range violates configured capacity")

    # Basilisk GroundLocation station access is cross-checked independently.
    mask = math.radians(float(cfg_radio["ground_station"]["minimum_elevation_deg"]))
    independent = np.array([
        elevation_from_inertial(tuple(p), tuple(q)) for p,q in zip(sc_r_N, station_r_N)
    ])
    safely_away = np.abs(independent-mask) > 1e-6
    if np.any(station[safely_away] != (independent[safely_away] >= mask)):
        raise AssertionError("Ground station access conflicts with independent geometry")

    actual_boresight_deg = np.array([
        true_boresight_error_deg(s, p, q, boresight_B)
        for s,p,q in zip(sigma_BN, sc_r_N, target_r_N)
    ], dtype=float)
    mrp_errors = np.linalg.norm(np.asarray(adcs_guid_sigma, dtype=float), axis=1)
    rate_errors = np.linalg.norm(np.asarray(adcs_guid_rate, dtype=float), axis=1)
    for i in np.flatnonzero(shots):
        if (actual_boresight_deg[i] > math.degrees(4*math.atan(float(cfg_cap["maximum_attitude_mrp_error"]))) + 1e-4
            or mrp_errors[i] > float(cfg_cap["maximum_attitude_mrp_error"]) + 1e-7
            or rate_errors[i] > float(cfg_cap["maximum_rate_error_rad_s"]) + 1e-7):
            raise AssertionError(
                f"Synthetic data produced without actual pointing readiness at t={time[i]}"
            )

    # Basilisk's PartitionedStorageUnit uses Euler integration over Δt.
    # Generation is an impulse in one step, radio is an integrated negative rate.
    generated_cumulative = np.r_[0, np.cumsum(generating[1:] * np.diff(time))]
    downlinked_cumulative = np.r_[0, np.cumsum((-sending[1:]) * np.diff(time))]
    generated_total = float(generated_cumulative[-1])
    downlinked_total = float(downlinked_cumulative[-1])
    if generated_total <= 0:
        raise AssertionError("Mission 01 must generate its test product")
    if abs(generated_total-bits_product) > 0.5:
        raise AssertionError(
            f"Expected one {bits_product} bit product, got {generated_total}"
        )
    # Unsent data remains in memory; no independent transmission loss model.
    # We explicitly retain the balance error instead of silently forcing 0.
    final_stored = float(stored[-1])
    conservation_error = generated_total - downlinked_total - final_stored
    if abs(conservation_error) > max(1.0, dt*float(cfg_radio["rate_bits_per_s"])*2):
        raise AssertionError(f"Data accounting inconsistent: {conservation_error} bits")

    events = np.flatnonzero(shots > 0)
    if len(events) != 1:
        raise AssertionError("Mission 01 expects exactly one synthetic capture")
    first_downlink_idx = np.flatnonzero(sending < 0)
    capture_time = float(time[events[0]])
    transmit_start = float(time[first_downlink_idx[0]]) if len(first_downlink_idx) else None
    # Delivered = actual negative transmitter baud integrated over time.
    completed = bool(downlinked_total >= bits_product - max(1., dt*float(cfg_radio["rate_bits_per_s"])))
    completed_idx = np.flatnonzero(downlinked_cumulative >= bits_product - max(1., dt*float(cfg_radio["rate_bits_per_s"])))
    completed_time = float(time[completed_idx[0]]) if completed and len(completed_idx) else None

    report = {
        "scenario": config["scenario_id"],
        "samples": n,
        "last_time_s": float(time[-1]),
        "step_s": dt,
        "capture_count": len(events),
        "capture_time_s": capture_time,
        "capture_actual_boresight_error_deg": float(actual_boresight_deg[events[0]]),
        "capture_tracking_mrp_norm": float(mrp_errors[events[0]]),
        "capture_tracking_rate_error_rad_s": float(rate_errors[events[0]]),
        "generated_bits": generated_total,
        "downlinked_bits": downlinked_total,
        "final_stored_bits": final_stored,
        "maximum_stored_bits": float(np.max(stored)),
        "capacity_bits": capacity_bits,
        "memory_utilization_max_fraction": float(np.max(stored)/capacity_bits),
        "data_conservation_error_bits": conservation_error,
        "station_access_samples": int(np.sum(station)),
        "station_windows": access_windows(time.tolist(), station.tolist()),
        "transmitting_samples": int(np.sum(sending < 0)),
        "first_transmission_time_s": transmit_start,
        "delivery_fraction": float(min(1., downlinked_total/generated_total)),
        "fully_delivered_within_sampling_tolerance": completed,
        "delivery_completion_time_s": completed_time,
        "data_latency_capture_to_delivery_s": (
            completed_time-capture_time if completed_time is not None else None
        ),
        "checks_passed": True,
        "limitations": [
            "This is a one-product synthetic test, not a pixel-resolved image",
            "A storage-bit decrement is treated as downlink delivery (no reception/ACK/errors)",
            "Ground station access is geometric with a spherical rotating Earth, no UTC",
            "Fixed perfect radio rate during access; no pointing, antenna gain or link budget",
            "Perfect simpleNav and unlimited ideal attitude torque, not flight actuators",
            "Finite-step window boundaries and transmission completion have time discretization error",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output/"mission_states.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "time_s", "target_access", "station_access", "boresight_error_deg",
            "capture_command", "generated_baud_bits_s", "stored_bits",
            "downlink_baud_bits_s", "cumulative_generated_bits",
            "cumulative_downlinked_bits"
        ])
        for row in zip(time, access, station, actual_boresight_deg, shots,
                       generating, stored, sending, generated_cumulative, downlinked_cumulative):
            ti, ta, sa, err, cmd, gen, memory, tx, cgen, ctx = row
            writer.writerow([
                float(ti), int(ta), int(sa), float(err), int(cmd), float(gen),
                float(memory), float(tx), float(cgen), float(ctx)
            ])
    (output/"mission_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(time/60, stored/8e6, label="Stored data (MB, decimal)")
    ax.plot(time/60, downlinked_cumulative/8e6, label="Downlinked data (MB, decimal)")
    ax.axhline(capacity_bits/8e6, linestyle="--", label="Storage capacity (MB)")
    ax.fill_between(time/60, 0, capacity_bits/8e6, where=station,
                    alpha=0.07, label="Station access")
    ax.set(xlabel="Elapsed model time (min)", ylabel="Data volume (MB)",
           title="Mission 01: generation, onboard accumulation and fixed-rate downlink")
    ax.grid(True);ax.legend();fig.tight_layout()
    fig.savefig(output/"mission_dataflow.png", dpi=150)
    plt.close(fig)
    return report
