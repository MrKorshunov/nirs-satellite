"""Deterministic union coverage of actually captured Basilisk nadir swath lines.

Coverage is ground-cell intersection in a local metric (WGS84 meridional /
prime-vertical curvature or spherical benchmark). Unlike summing strip areas,
each covered geographic grid cell is counted ONCE; overlap is not double
counted. Explicit grid-resolution and convergence estimates prevent mistaking
this discretization for exact polygon clipping.
"""
from __future__ import annotations
import math
from experiments.mission_03.swath_geometry import _wrap
from experiments.mission_03.geo_time import WGS84_A,WGS84_E2

def local_metrics(lat0_deg,ellipsoid):
    lat=math.radians(lat0_deg)
    if ellipsoid:
        denom=1-WGS84_E2*math.sin(lat)**2
        m=WGS84_A*(1-WGS84_E2)/denom**1.5
        n=WGS84_A/math.sqrt(denom)
        return m,n*math.cos(lat)
    return 6378137.,6378137.*math.cos(lat)

def _project(lat,lon,lat0,lon0,my,mx):
    return (mx*math.radians(_wrap(lon-lon0)),
            my*math.radians(lat-lat0))

def _inside(x,y,ring):
    flag=False
    for (ax,ay),(bx,by) in zip(ring,ring[1:]+ring[:1]):
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:
            flag=not flag
    return flag

def _near_segment(px,py,ax,ay,bx,by,half_width):
    dx=bx-ax;dy=by-ay
    d2=dx*dx+dy*dy
    if d2<1e-9:
        return False
    u=((px-ax)*dx+(py-ay)*dy)/d2
    if not 0<=u<=1:
        return False
    return abs((px-ax)*dy-(py-ay)*dx)<=half_width*math.sqrt(d2)

def _coverage_grid(reg,lines,ellipsoid,step_limit):
    polygon=reg["polygon_lat_lon_deg"]
    lat0=sum(p[0] for p in polygon)/len(polygon)
    lon0=sum(p[1] for p in polygon)/len(polygon)
    my,mx=local_metrics(lat0,ellipsoid)
    ring=[_project(p[0],p[1],lat0,lon0,my,mx) for p in polygon]
    xmin=min(p[0] for p in ring);xmax=max(p[0] for p in ring)
    ymin=min(p[1] for p in ring);ymax=max(p[1] for p in ring)
    nominal=max(250.,math.sqrt((xmax-xmin)*(ymax-ymin)/step_limit))
    nx=max(1,math.ceil((xmax-xmin)/nominal))
    ny=max(1,math.ceil((ymax-ymin)/nominal))
    dx=(xmax-xmin)/nx;dy=(ymax-ymin)/ny
    # Convert each actually observed contiguous line's previous geodetic
    # groundpoint and current point into a swept rectangle; width is the
    # recorded nadir transverse FOV projected to the local tangent plane.
    segments=[]
    for line in lines:
        if line.get("previous_lat_deg") is None:
            continue
        ax,ay=_project(line["previous_lat_deg"],line["previous_lon_deg"],
                       lat0,lon0,my,mx)
        bx,by=_project(line["lat_deg"],line["lon_deg"],lat0,lon0,my,mx)
        half=float(line["swath_width_m"])*0.5
        if math.hypot(bx-ax,by-ay)<1:
            continue
        segments.append((ax,ay,bx,by,half,
                         min(ax,bx)-half,max(ax,bx)+half,
                         min(ay,by)-half,max(ay,by)+half))
    inside_count=covered_count=0
    for row in range(ny):
        y=ymin+(row+0.5)*dy
        for col in range(nx):
            x=xmin+(col+0.5)*dx
            if not _inside(x,y,ring):
                continue
            inside_count+=1
            for a,b,c,d,w,l,r,bottom,top in segments:
                if not (l<=x<=r and bottom<=y<=top):
                    continue
                if _near_segment(x,y,a,b,c,d,w):
                    covered_count+=1
                    break
    area=dx*dy
    return {
        "region_area_m2":inside_count*area,
        "covered_area_m2":covered_count*area,
        "coverage_percent":100.*covered_count/inside_count if inside_count else 0.,
        "grid_size_m":math.sqrt(area),
        "region_cells":inside_count,
        "covered_cells":covered_count,
        "capture_segments":len(segments),
        "total_grid_cells":nx*ny,
    }

def compute_coverage(regions:dict,lines:list,*,ellipsoid:bool=False,
                     coarse_cells:int=50000,fine_cells:int=120000)->dict:
    if not 1000<=coarse_cells<fine_cells<=500000:
        raise ValueError("Need bounded increasing coverage grid resolution")
    result={}
    for id,region in regions.items():
        observed=[line for line in lines if line["task_region_id"]==id]
        coarse=_coverage_grid(region,observed,ellipsoid,coarse_cells)
        fine=_coverage_grid(region,observed,ellipsoid,fine_cells)
        result[id]={
            **fine,
            "coarse_coverage_percent":coarse["coverage_percent"],
            "grid_convergence_delta_percentage_points":abs(
                fine["coverage_percent"]-coarse["coverage_percent"]),
            "method":"union_of_captured_along_track_rectangles_raster_cells",
            "geodesy":"WGS84_local_curvature" if ellipsoid else "local_spherical_metric",
            "is_exact_polygon_clipping":False,
            "uncertainty_warning":"Grid-cell discretization only; convergence delta is not a rigorous total error bound",
        }
    return result
