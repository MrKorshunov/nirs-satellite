"""Orbit-ground-track and synthetic nadir strip footprint geometry.

Works in a planet-fixed spherical frame. Polygon coordinates are degrees
(latitude, longitude); short-region local equirectangular metric is explicit.
No terrain, camera pixel model, clouds, precise geodetic ellipsoid or UTC.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

def _wrap(lon:float)->float:
    return (lon+180.0)%360.0-180.0

def _xy(lat:float,lon:float,lat0:float,lon0:float,radius:float)->tuple[float,float]:
    return (radius*math.cos(math.radians(lat0))*math.radians(_wrap(lon-lon0)),
            radius*math.radians(lat-lat0))

def validate_regions(cfg:dict)->dict[str,dict]:
    if not str(cfg.get("provenance","")).startswith("SYNTHETIC"):
        raise ValueError("Region source must state synthetic provenance")
    if cfg.get("frame") not in ("planet_fixed_spherical_lat_lon_deg","wgs84_geodetic_deg"):
        raise ValueError("Expected Earth-fixed spherical or WGS84 geodetic lat/lon region frame")
    regions=cfg.get("regions")
    if not isinstance(regions,list) or not regions:
        raise ValueError("At least one bounded Earth-fixed region is required")
    index={}
    for reg in regions:
        key=reg["id"]
        if not isinstance(key,str) or not key.isascii() or not key or key in index:
            raise ValueError("Region identifiers must be distinct ASCII")
        ring=reg["polygon_lat_lon_deg"]
        if len(ring)<3 or len(ring)>64:
            raise ValueError("Region needs 3..64 polygon vertices")
        if any(len(v)!=2 or not all(math.isfinite(float(x)) for x in v)
               or not -90<=float(v[0])<=90 or not -180<=float(v[1])<=180 for v in ring):
            raise ValueError("Invalid region vertices")
        lats=[float(v[0]) for v in ring]
        lon=[float(v[1]) for v in ring]
        if max(lats)-min(lats)>12 or max(lon)-min(lon)>12:
            raise ValueError("Region polygon must fit a 12-degree local projection; split very large areas")
        if max(lats)-min(lats)<1e-6 or max(lon)-min(lon)<1e-6:
            raise ValueError("Zero-area region polygon")
        index[key]=reg
    return index

def _distance_segment(x,y,ax,ay,bx,by):
    dx=bx-ax;dy=by-ay
    norm=dx*dx+dy*dy
    q=0.0 if norm==0 else min(1.0,max(0.0,((x-ax)*dx+(y-ay)*dy)/norm))
    return math.hypot(x-(ax+q*dx),y-(ay+q*dy))

def polygon_distance_m(lat:float,lon:float,polygon:list,radius:float)->float:
    """Signed distance in a local tangent projection; negative if inside."""
    lat0=sum(float(p[0]) for p in polygon)/len(polygon)
    lon0=sum(float(p[1]) for p in polygon)/len(polygon)
    x,y=_xy(lat,lon,lat0,lon0,radius)
    points=[_xy(float(p[0]),float(p[1]),lat0,lon0,radius) for p in polygon]
    inside=False
    minimum=float("inf")
    for (ax,ay),(bx,by) in zip(points,points[1:]+points[:1]):
        minimum=min(minimum,_distance_segment(x,y,ax,ay,bx,by))
        if (ay>y)!=(by>y):
            xx=ax+(y-ay)*(bx-ax)/(by-ay)
            if x<xx:
                inside=not inside
    return -minimum if inside else minimum

def nadir_footprint_width_m(altitude_m:float,field_of_view_deg:float)->float:
    """Flat local surface approximation valid for modest h/R and narrow FOV."""
    if not math.isfinite(altitude_m) or altitude_m<=0:
        raise ValueError("Altitude must be positive")
    if not 0<float(field_of_view_deg)<60:
        raise ValueError("Limited nadir cross-track field of view must be in (0,60) degrees")
    return 2.0*altitude_m*math.tan(math.radians(field_of_view_deg)*0.5)

def swath_intersects_region(lat:float,lon:float,altitude_m:float,fov_deg:float,
                             polygon:list,radius_m:float)->tuple[bool,float,float]:
    width=nadir_footprint_width_m(altitude_m,fov_deg)
    distance=polygon_distance_m(lat,lon,polygon,radius_m)
    return distance<=width*0.5,distance,width

def ground_point_from_position(
    position_N_m,rotation_J2000_to_Pfix,radius_m,geodetic=False
)->tuple[float,float,float]:
    """Spherical subsatellite footpoint using actual Basilisk planet DCM."""
    if len(position_N_m)!=3:
        raise ValueError("Expected 3D inertial spacecraft position")
    # Basilisk SpicePlanetState.J20002Pfix is a 3x3 passive DCM.
    rot=rotation_J2000_to_Pfix
    if len(rot)==9 and not hasattr(rot[0],"__len__"):
        rot=[rot[0:3],rot[3:6],rot[6:9]]
    p=[sum(float(rot[i][k])*float(position_N_m[k]) for k in range(3))
       for i in range(3)]
    mag=math.sqrt(sum(z*z for z in p))
    if mag<=radius_m:
        raise ValueError("Spacecraft below spherical Earth reference")
    if geodetic:
        from experiments.mission_03.geo_time import ecef_to_geodetic
        return ecef_to_geodetic(p)
    latitude=math.degrees(math.asin(max(-1.,min(1.,p[2]/mag))))
    longitude=_wrap(math.degrees(math.atan2(p[1],p[0])))
    return latitude,longitude,mag-radius_m

def great_circle_distance_m(a:tuple[float,float],b:tuple[float,float],radius_m:float)->float:
    p1,l1=map(math.radians,a)
    p2,l2=map(math.radians,b)
    delta=p2-p1;lam=l2-l1
    h=math.sin(delta/2)**2+math.cos(p1)*math.cos(p2)*math.sin(lam/2)**2
    return 2*radius_m*math.asin(min(1.,math.sqrt(max(0.,h))))
