"""Reproducible UTC anchor, approximate GMST, and WGS84 geodetic conversions.

USNO approximate Greenwich mean sidereal time uses UTC as UT1 proxy.
There is no EOP/polar motion, leap-second propagation or precession/nutation;
this is explicitly a dated engineering geometry, not sub-arcsecond ITRF.
NGA WGS84 constants: a=6378137 m, inverse flattening=298.257223563.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
import math

WGS84_A=6378137.0
WGS84_F=1./298.257223563
WGS84_E2=WGS84_F*(2-WGS84_F)

def parse_utc(value:str)->datetime:
    if not isinstance(value,str):
        raise ValueError("epoch_utc must be ISO 8601 UTC string")
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid ISO 8601 UTC epoch") from exc
    if dt.utcoffset()!=timedelta(0):
        raise ValueError("epoch_utc must explicitly use UTC timezone offset +00:00 or Z")
    if not 2000<=dt.year<=2100:
        raise ValueError("Approximate sidereal model validated for 2000..2100")
    return dt.astimezone(timezone.utc)

def gmst_degrees(utc:datetime,ut1_minus_utc_s:float=0.0)->float:
    """USNO approximation, JD_UT ~= JD_TT, with user-specified DUT1."""
    if utc.tzinfo is None:
        raise ValueError("UTC must be timezone aware")
    if not math.isfinite(float(ut1_minus_utc_s)) or abs(ut1_minus_utc_s)>1.0:
        raise ValueError("DUT1 must be finite and within +/- 1 second")
    ut=utc.astimezone(timezone.utc)+timedelta(seconds=float(ut1_minus_utc_s))
    jd=ut.timestamp()/86400.+2440587.5
    midnight=datetime(ut.year,ut.month,ut.day,tzinfo=timezone.utc)
    jd0=midnight.timestamp()/86400.+2440587.5
    d=jd0-2451545.0
    h=(ut-midnight).total_seconds()/3600.
    t=(jd-2451545.0)/36525.
    gmst_h=(6.697375+0.065709824279*d+1.0027379*h+0.0000258*t*t)%24.
    return gmst_h*15.

def epoch_parameters(cfg:dict)->dict:
    if cfg.get("time_frame_mode","synthetic")=="synthetic":
        return {"mode":"synthetic","epoch_utc":None,
                "reference_frame":"synthetic_rotating_sphere"}
    if cfg.get("time_frame_mode")!="utc_approx_wgs84":
        raise ValueError("Unsupported time/earth reference mode")
    dt=parse_utc(cfg["epoch_utc"])
    dut=float(cfg.get("ut1_minus_utc_s",0.0))
    return {"mode":"utc_approx_wgs84",
            "epoch_utc":dt.isoformat().replace("+00:00","Z"),
            "ut1_minus_utc_s":dut,
            "gmst_at_epoch_deg":gmst_degrees(dt,dut),
            "reference_frame":"approx_GMST_J2000_to_ECEF_with_WGS84_geodetic_reporting",
            "limitations":[
                "UTC is a start-time anchor; UT1-UTC must be sourced from EOP for high accuracy",
                "No polar motion, nutation/precession/ERA frame corrections or SPICE epoch propagation",
                "Basilisk dynamics and groundLocation remain spherical in this benchmark",
                "WGS84 geodetic positions and coverage projection are accurate ellipsoid conversions, not full orbit geolocation",
            ]}

def ecef_to_geodetic(xyz)->tuple[float,float,float]:
    x,y,z=(float(v) for v in xyz)
    p=math.hypot(x,y)
    if p<1.:
        raise ValueError("ECEF polar-axis input not supported in this mission")
    lon=math.atan2(y,x)
    lat=math.atan2(z,p*(1-WGS84_E2))
    for _ in range(12):
        s=math.sin(lat)
        n=WGS84_A/math.sqrt(1-WGS84_E2*s*s)
        height=p/math.cos(lat)-n
        new=math.atan2(z,p*(1-WGS84_E2*n/(n+height)))
        if abs(new-lat)<1e-13:
            lat=new
            break
        lat=new
    n=WGS84_A/math.sqrt(1-WGS84_E2*math.sin(lat)**2)
    h=p/math.cos(lat)-n
    return math.degrees(lat),math.degrees(lon),h

def geodetic_to_ecef(lat_deg:float,lon_deg:float,h_m:float=0.0):
    lat=math.radians(lat_deg);lon=math.radians(lon_deg)
    s=math.sin(lat)
    n=WGS84_A/math.sqrt(1.-WGS84_E2*s*s)
    return ((n+h_m)*math.cos(lat)*math.cos(lon),
            (n+h_m)*math.cos(lat)*math.sin(lon),
            (n*(1.-WGS84_E2)+h_m)*s)

def geocentric_latitude_for_geodetic(lat_deg:float,h_m:float=0.0)->float:
    x,y,z=geodetic_to_ecef(lat_deg,0.,h_m)
    return math.degrees(math.atan2(z,math.hypot(x,y)))

def utc_at_elapsed(epoch_iso:str,t_seconds:float)->str:
    return (parse_utc(epoch_iso)+timedelta(seconds=float(t_seconds))).isoformat().replace("+00:00","Z")
