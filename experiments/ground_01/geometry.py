"""Independent, stdlib-only checks and helpers for ground access geometry.

Coordinate frames: inertial Earth-centred N for satellite/ground Cartesian
vectors; local vertical defined by spherical Earth centre-to-target radial.
This is not geodetic WGS84 or a real epoch/Greenwich rotation model.
"""
from __future__ import annotations

from math import asin, cos, degrees, radians, sin, sqrt


def norm3(v: tuple[float, float, float]) -> float:
    return sqrt(sum(x * x for x in v))


def dot3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum(x*y for x,y in zip(a,b))


def rotate_z(v: tuple[float, float, float], angle_rad: float) -> tuple[float, float, float]:
    c,s=cos(angle_rad),sin(angle_rad)
    return (v[0]*c-v[1]*s, v[0]*s+v[1]*c, v[2])


def elevation_from_inertial(
    spacecraft_m: tuple[float,float,float],
    ground_m: tuple[float,float,float]
) -> float:
    """Elevation in radians relative to local spherical zenith."""
    gr=norm3(ground_m)
    if gr<=0:
        raise ValueError("Ground location cannot be at Earth centre")
    los=tuple(a-b for a,b in zip(spacecraft_m,ground_m))
    rng=norm3(los)
    if rng<=0:
        raise ValueError("Spacecraft position must differ from ground position")
    v=dot3(los,ground_m)/(rng*gr)
    return asin(max(-1.0,min(1.0,v)))


def access_windows(times_s: list[float], access: list[bool]) -> list[dict]:
    """Extract sample-resolved access windows; limits uncertain by one step."""
    if not times_s or len(times_s)!=len(access):
        raise ValueError("Expected same-length nonempty time and access series")
    if any(b<=a for a,b in zip(times_s,times_s[1:])):
        raise ValueError("Times must strictly increase")
    out=[]
    start=None
    for idx,(t,a) in enumerate(zip(times_s,access)):
        if a and start is None:
            start=t
        if not a and start is not None:
            out.append({"first_access_sample_s":start,
                        "first_inaccessible_sample_s":t,
                        "duration_upper_bound_s":t-start,
                        "window_start_clipped":start==times_s[0],
                        "window_end_clipped":False})
            start=None
    if start is not None:
        step=times_s[-1]-times_s[-2] if len(times_s)>1 else 0.0
        out.append({"first_access_sample_s":start,
                    "first_inaccessible_sample_s":times_s[-1]+step,
                    "duration_upper_bound_s":times_s[-1]+step-start,
                    "window_start_clipped":start==times_s[0],
                    "window_end_clipped":True})
    return out
