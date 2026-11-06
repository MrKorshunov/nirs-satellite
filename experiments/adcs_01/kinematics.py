"""Independent SI-unit attitude/line-of-sight geometry, standard library only.

Basilisk does not get imported here. For MRP sigma_BN, [BN] is the passive
DCM rotating inertial vector components into body components.
"""
from __future__ import annotations

import math
from typing import Sequence


def _vec3(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("Expected exactly three vector components")
    v = tuple(float(x) for x in values)
    if any(not math.isfinite(x) for x in v):
        raise ValueError("Non-finite vector")
    return v


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(sum(x*x for x in v))


def mrp_dcm_BN(sigma: Sequence[float]) -> tuple[tuple[float, ...], ...]:
    """Passive 3x3 [BN] DCM; follows standard unit-quaternion/MRP relation."""
    s = _vec3(sigma)
    s2 = sum(x*x for x in s)
    q0 = (1.0 - s2)/(1.0 + s2)
    q = tuple(2.0*x/(1.0+s2) for x in s)
    q2 = sum(x*x for x in q)
    skew = ((0, -q[2], q[1]),
            (q[2], 0, -q[0]),
            (-q[1], q[0], 0))
    return tuple(tuple(
        (q0*q0-q2)*(1.0 if i==j else 0.0)
        + 2.0*q[i]*q[j] - 2.0*q0*skew[i][j]
        for j in range(3)
    ) for i in range(3))


def true_boresight_error_deg(
    sigma_BN: Sequence[float],
    spacecraft_position_N_m: Sequence[float],
    target_position_N_m: Sequence[float],
    boresight_B: Sequence[float],
) -> float:
    """Angle between actual body-fixed pointing axis and inertial target LOS."""
    sat = _vec3(spacecraft_position_N_m)
    target = _vec3(target_position_N_m)
    b = _vec3(boresight_B)
    if not math.isclose(_norm(b), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Body boresight must be a unit vector")
    los = tuple(bi-ai for ai, bi in zip(sat, target))
    length = _norm(los)
    if length <= 0:
        raise ValueError("Undefined target vector")
    C = mrp_dcm_BN(sigma_BN)
    # [NB]=[BN].T, thus (B -> N) components indexed as C[j][i].
    b_inertial = tuple(sum(C[i][j]*b[i] for i in range(3)) for j in range(3))
    dot = sum(a*b for a,b in zip(b_inertial, los)) / length
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def dcm_orthogonality_error(sigma_BN: Sequence[float]) -> float:
    C = mrp_dcm_BN(sigma_BN)
    return max(abs(sum(C[k][i]*C[k][j] for k in range(3)) -
                   (1.0 if i==j else 0.0))
               for i in range(3) for j in range(3))
