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


def mrp_to_dcm(sigma: np.ndarray) -> np.ndarray:
    """Passive DCM [BN] from modified Rodrigues parameters sigma_BN."""
    x = np.asarray(sigma, dtype=float)
    if x.shape != (3,) or not np.all(np.isfinite(x)):
        raise ValueError("Expected finite 3-component attitude MRP")
    ss = float(np.dot(x, x))
    skew = np.array([[0, -x[2], x[1]],
                     [x[2], 0, -x[0]],
                     [-x[1], x[0], 0]], dtype=float)
    identity = np.eye(3)
    return identity + (8 * (skew @ skew) - 4 * (1 - ss) * skew) / (1 + ss) ** 2


def true_boresight_error_deg(
    sigma_BN: np.ndarray,
    spacecraft_position_N_m: np.ndarray,
    target_position_N_m: np.ndarray,
    pHat_B: np.ndarray,
) -> float:
    """Actual 3D angle between spacecraft-fixed sensor axis and target LOS."""
    los = np.asarray(target_position_N_m, float) - np.asarray(spacecraft_position_N_m, float)
    length = float(np.linalg.norm(los))
    if length <= 0 or not math.isfinite(length):
        raise ValueError("Undefined target direction")
    b = np.asarray(pHat_B, float)
    if b.shape != (3,) or not math.isclose(float(np.linalg.norm(b)), 1.0, abs_tol=1e-9):
        raise ValueError("Boresight must be a unit 3-vector")
    # [BN] transforms inertial to body components, so transpose goes B -> N.
    b_N = mrp_to_dcm(np.asarray(sigma_BN, float)).T @ b
    cosine = float(np.clip(np.dot(b_N, los/length), -1, 1))
    return math.degrees(math.acos(cosine))


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
        np.linalg.norm(mrp_to_dcm(s).T @ mrp_to_dcm(s) - np.eye(3))
        for s in sig
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
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
