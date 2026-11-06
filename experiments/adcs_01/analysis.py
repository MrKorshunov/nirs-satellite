"""Independent geometric diagnostics of a Basilisk ADCS run.

This module does not import Basilisk. It builds the passive body-from-inertial
DCM from physical-spacecraft MRPs to check the actual sensor boresight against
the inertial vector to the rotating-Earth target. It is NOT a flight-qualified
navigation, sensor or actuator validation.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np


from experiments.adcs_01.kinematics import (
    true_boresight_error_deg, dcm_orthogonality_error,
)


def analyse_run(
    *,
    time_s: np.ndarray,
    position_N_m: np.ndarray,
    target_N_m: np.ndarray,
    sigma_BN: np.ndarray,
    guidance_sigma_BR: np.ndarray,
    guidance_omega_BR_B: np.ndarray,
    torque_Nm: np.ndarray,
    has_access: np.ndarray,
    config: dict,
    output: Path,
) -> dict:
    t = np.asarray(time_s, dtype=float)
    r = np.asarray(position_N_m, dtype=float)
    g = np.asarray(target_N_m, dtype=float)
    sig = np.asarray(sigma_BN, dtype=float)
    guid = np.asarray(guidance_sigma_BR, dtype=float)
    rate = np.asarray(guidance_omega_BR_B, dtype=float)
    torque = np.asarray(torque_Nm, dtype=float)
    access = np.asarray(has_access, dtype=bool)
    n = len(t)
    if n < 3 or any(x.shape != (n, 3) for x in (r, g, sig, guid, rate, torque)) or access.shape != (n,):
        raise ValueError("ADCS recorder data must have N rows of 3-vectors and aligned access")
    if not np.all(np.diff(t)>0) or not all(np.all(np.isfinite(x)) for x in (t, r, g, sig, guid, rate, torque)):
        raise ValueError("Non-finite or non-increasing ADCS timeseries")

    axis = np.asarray(config["instrument_boresight_B"], dtype=float)
    angle = np.asarray(
        [true_boresight_error_deg(s, a, b, axis) for s, a, b in zip(sig, r, g)],
        dtype=float
    )
    # MRP angle is magnitude of total body/reference rotation, which includes
    # possible roll. It is different from the 2-axis line-of-sight angle.
    mrp_angle = np.degrees(4 * np.arctan(np.linalg.norm(guid, axis=1)))
    rate_norm = np.linalg.norm(rate, axis=1)
    torque_norm = np.linalg.norm(torque, axis=1)
    max_angle = float(config["readiness_boresight_max_deg"])
    max_rate = float(config["readiness_tracking_rate_max_rad_s"])
    ready = access & (angle <= max_angle) & (rate_norm <= max_rate)
    orth_error = float(max(
        dcm_orthogonality_error(s) for s in sig
    ))

    if orth_error > 1e-10:
        raise AssertionError("Independent MRP DCM is not orthogonal")
    if np.max(torque_norm) <= 1e-9:
        raise AssertionError("No commanded control torque: ADCS may be disconnected")
    if not np.any(np.abs(sig[0] - sig[-1]) > 1e-5):
        raise AssertionError("Spacecraft rotational dynamics did not evolve")

    output.mkdir(parents=True, exist_ok=True)
    with (output / "adcs_states.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "time_s", "sigma_BN_x", "sigma_BN_y", "sigma_BN_z",
            "boresight_error_deg", "mrp_tracking_error_deg",
            "tracking_rate_error_rad_s", "commanded_torque_norm_Nm",
            "has_ground_access", "capture_conditions_met",
        ])
        for row in zip(t, sig, angle, mrp_angle, rate_norm, torque_norm, access, ready):
            ti, si, ai, mi, wi, ui, visible, ok = row
            writer.writerow([
                float(ti), *[float(x) for x in si], float(ai), float(mi),
                float(wi), float(ui), int(visible), int(ok),
            ])
    # Figures are diagnostic views of recorded physical and guidance states.
    # Separate the pointing metric from the actuator torque for clarity.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t/60, angle, label="Actual boresight-to-target angle (deg)")
    ax.axhline(max_angle, linestyle="--", label="Synthetic readiness limit (deg)")
    ax.fill_between(t/60, 0, np.maximum(angle, max_angle),
                    where=access, alpha=0.08, label="Ground geometrically accessible")
    ax.set(xlabel="Elapsed model time (min)", ylabel="Pointing angular error (deg)",
           title="ADCS 01: actual rigid-body boresight, not ideal AttGuid")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "adcs_pointing.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t/60, torque_norm, label="Commanded ideal torque magnitude")
    ax.set(xlabel="Elapsed model time (min)", ylabel="Torque (N m)",
           title="ADCS 01: MRP feedback request (no hardware saturation)")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "adcs_torque.png", dpi=150)
    plt.close(fig)

    report = {
        "model": "Basilisk rigid-body orientation with ideal continuous external torque and perfect simpleNav",
        "samples": n,
        "first_time_s": float(t[0]),
        "last_time_s": float(t[-1]),
        "initial_boresight_error_deg": float(angle[0]),
        "minimum_boresight_error_deg": float(np.min(angle)),
        "final_boresight_error_deg": float(angle[-1]),
        "max_commanded_torque_Nm": float(np.max(torque_norm)),
        "initial_sigma_BN_mrp": [float(x) for x in sig[0]],
        "final_sigma_BN_mrp": [float(x) for x in sig[-1]],
        "access_samples": int(np.sum(access)),
        "pointing_ready_samples_during_access": int(np.sum(ready)),
        "first_pointing_ready_time_s": float(t[np.flatnonzero(ready)[0]]) if np.any(ready) else None,
        "maximum_mrp_dcm_orthogonality_error": orth_error,
        "readiness_boresight_max_deg": max_angle,
        "readiness_tracking_rate_max_rad_s": max_rate,
        "checks_passed": True,
        "limits_of_interpretation": [
            "A commanded ideal torque is applied to rigid-body dynamics without a hardware torque limit",
            "The navigation message is an idealized truth-like estimate without sensor noise",
            "The controller tracks the ground direction EVEN when geometric Earth access is false",
            "Pointing readiness is an ANALYTICAL FLAG, not execution of camera exposure or storage",
            "No real camera FOV, actuator wheel momentum, energy, jitter or UTC epoch",
        ],
    }
    (output / "adcs_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
