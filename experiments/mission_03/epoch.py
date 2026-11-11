"""UTC reference and bounded-accuracy sidereal Earth orientation.

The IAU 1982 approximate GMST series is used with UT1 = UTC + dut1_seconds.
The value anchors the same synthetic rotating-Earth Basilisk planetEphemeris
instead of leaving the longitude at an arbitrary t=0. This is *not* an ITRF
Earth orientation solution: no IERS polar motion, precession/nutation/EOP, or
high-precision J2000-of-date transform. Document residual model errors.
References: USNO Approximate Sidereal Time; JPL Metric Prediction Generation.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import math

def read_epoch(text:str)->datetime:
    if not isinstance(text,str) or not text.endswith("Z"):
        raise ValueError("epoch_utc must be an ISO-8601 UTC string ending in Z")
    try:
        result=datetime.fromisoformat(text[:-1]+"+00:00")
    except ValueError as exc:
        raise ValueError("Invalid ISO 8601 UTC epoch") from exc
    if not 2000<=result.year<=2100 or result.utcoffset()!=timedelta(0):
        raise ValueError("UTC epoch must be between 2000 and 2100")
    return result

def julian_date(dt:datetime)->float:
    if dt.tzinfo is None or dt.utcoffset()!=timedelta(0):
        raise ValueError("Julian day requires timezone-aware UTC datetime")
    return dt.timestamp()/86400.0+2440587.5

def gmst_deg(epoch_utc:str,dut1_seconds:float=0.0)->float:
    """Approximate Greenwich mean sidereal time (IAU 1982, degrees).

    UT1-UTC must be supplied by user for high-fidelity experiments.
    No leap-second interpolation, IERS precession, nutation or polar motion.
    """
    if not math.isfinite(float(dut1_seconds)) or abs(float(dut1_seconds))>0.9:
        raise ValueError("DUT1 is finite and must be within +/-0.9 s")
    dt=read_epoch(epoch_utc)+timedelta(seconds=float(dut1_seconds))
    d=julian_date(dt)-2451545.0
    t=d/36525.0
    return (280.46061837+360.98564736629*d+0.000387933*t*t
            -t*t*t/38710000.0)%360.0

def date_at(epoch_utc:str,seconds:float)->str:
    if not math.isfinite(float(seconds)):
        raise ValueError("Simulation offset must be finite")
    return (read_epoch(epoch_utc)+timedelta(seconds=float(seconds))
            ).isoformat(timespec="milliseconds").replace("+00:00","Z")

def epoch_metadata(cfg:dict)->dict|None:
    if "epoch_utc" not in cfg:
        return None
    epoch=cfg["epoch_utc"]
    dut1=float(cfg.get("dut1_seconds",0.0))
    return {
        "epoch_utc":read_epoch(epoch).isoformat().replace("+00:00","Z"),
        "dut1_seconds":dut1,
        "gmst_start_deg":gmst_deg(epoch,dut1),
        "model":"IAU1982_GMST_UTCplusDUT1_fixed_Earth_spin_J2000_approx",
        "reference_frame_warning":"GMST of date, but simplified Basilisk J2000 fixed pole: no EOP, nutation, precession, polar motion or ITRF transformation",
        "utc_is_not_UT1":True,
    }
