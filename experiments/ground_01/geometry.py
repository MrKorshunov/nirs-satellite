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
    """Extract sampled windows and conservative crossing-time bounds.

    Assumes one continuous entrance/exit around each sampled access run,
    with no undetected multiple threshold crossings between samples.
    The first/last accessible samples are NOT exact threshold times.
    """
    if not times_s or len(times_s) != len(access):
        raise ValueError("Expected same-length nonempty time and access series")
    if any(b <= a for a, b in zip(times_s, times_s[1:])):
        raise ValueError("Times must strictly increase")

    def describe(start_idx: int, end_exclusive: int) -> dict:
        first = times_s[start_idx]
        last = times_s[end_exclusive - 1]
        previous = times_s[start_idx - 1] if start_idx else None
        following = times_s[end_exclusive] if end_exclusive < len(times_s) else None
        clipped_start = previous is None
        clipped_end = following is None
        return {
            "first_access_sample_s": first,
            "last_access_sample_s": last,
            "previous_inaccessible_sample_s": previous,
            "first_inaccessible_sample_s": following,
            # The true onset is between (previous, first] if un-clipped.
            "start_bound_earliest_s": previous,
            "start_bound_latest_s": first,
            # The true exit is between (last, following] if un-clipped.
            "end_bound_earliest_s": last,
            "end_bound_latest_s": following,
            "duration_lower_bound_s": last - first,
            # Previously this was following-first, which is NOT an upper bound:
            # onset may occur earlier than the first accessible sample.
            "duration_upper_bound_s": (
                following - previous if not clipped_start and not clipped_end
                else None
            ),
            "window_start_clipped": clipped_start,
            "window_end_clipped": clipped_end,
        }

    windows = []
    start_idx = None
    for i, available in enumerate(access):
        if available and start_idx is None:
            start_idx = i
        elif not available and start_idx is not None:
            windows.append(describe(start_idx, i))
            start_idx = None
    if start_idx is not None:
        windows.append(describe(start_idx, len(times_s)))
    return windows
