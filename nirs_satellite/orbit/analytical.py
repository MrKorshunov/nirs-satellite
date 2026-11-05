"""Two-body reference formulas used to verify orbit simulations.

These formulas are independent of Basilisk. SI units throughout.
They are *not* an alternative numerical orbit propagator.
"""

from math import pi, sqrt


def orbital_period_s(semi_major_axis_m: float, mu_m3_s2: float) -> float:
    """Keplerian period in seconds for a bound two-body orbit."""
    if semi_major_axis_m <= 0 or mu_m3_s2 <= 0:
        raise ValueError("Semi-major axis and gravitational parameter must be positive")
    return 2 * pi * sqrt(semi_major_axis_m**3 / mu_m3_s2)


def circular_speed_m_s(radius_m: float, mu_m3_s2: float) -> float:
    """Two-body circular orbital speed, in metres per second."""
    if radius_m <= 0 or mu_m3_s2 <= 0:
        raise ValueError("Radius and gravitational parameter must be positive")
    return sqrt(mu_m3_s2 / radius_m)


def relative_span(values: list[float]) -> float:
    """(max - min) / abs(initial); useful for energy and momentum checks."""
    if not values or values[0] == 0:
        raise ValueError("Expected a nonempty series with nonzero initial value")
    return (max(values) - min(values)) / abs(values[0])
