"""Footprint/territory intersection with WGS84 equal-area area accounting.

Each actually-produced Basilisk camera line is represented by a ground-track
rectangular swath footprint: a *modeled* instantaneously acquired area, not
pixels. The WGS84 azimuthal equal-area projection preserves region/union areas;
Shapely unions overlapping footprints before clipping, so coverage is never
double-counted. Bounds are local <12 degrees from region validation.

Coverage can be zero even when a synthetic camera product was generated.
No cloud, terrain, optical smear, real instantaneous cross-track pointing/FOV
ray-tracing, sensor distortion or actual ground sampling distance.
"""
from __future__ import annotations
from collections import defaultdict
import math

from experiments.mission_03.swath_geometry import nadir_footprint_width_m


def _region_projection(polygon):
    from pyproj import CRS,Transformer
    from shapely.geometry import Polygon
    lat0=sum(v[0] for v in polygon)/len(polygon)
    lon0=sum(v[1] for v in polygon)/len(polygon)
    proj=CRS.from_proj4(
        f"+proj=laea +lat_0={lat0:.10f} +lon_0={lon0:.10f} "
        "+datum=WGS84 +units=m +no_defs +type=crs"
    )
    to_local=Transformer.from_crs(CRS.from_epsg(4326),proj,always_xy=True)
    to_lonlat=Transformer.from_crs(proj,CRS.from_epsg(4326),always_xy=True)
    target=Polygon([to_local.transform(float(lon),float(lat))
                    for lat,lon in polygon])
    if not target.is_valid or target.area<=0:
        raise ValueError("Territory polygon must be simple, non-self-intersecting, positive area")
    return to_local,to_lonlat,target


def _footprint_at(t:float,lat:float,lon:float,width_m:float,
                  sample_dt_s:float,trajectory:list,project):
    from shapely.geometry import LineString
    if width_m<=0 or sample_dt_s<=0:
        raise ValueError("Invalid swath width or sample duration")
    if len(trajectory)<2:
        raise ValueError("At least two true Basilisk orbit samples required")
    # Track time is monotonic. We use closest before/after to determine
    # instantaneous projected velocity (no estimated orbit approximation).
    i=min(range(len(trajectory)),key=lambda j:abs(float(trajectory[j]["t_s"])-t))
    first=trajectory[max(0,i-1)]
    last=trajectory[min(len(trajectory)-1,i+1)]
    dt=float(last["t_s"])-float(first["t_s"])
    if dt<=0:
        raise ValueError("Degenerate physical ground track")
    x,y=project.transform(float(lon),float(lat))
    ax,ay=project.transform(float(first["lon_deg"]),float(first["lat_deg"]))
    bx,by=project.transform(float(last["lon_deg"]),float(last["lat_deg"]))
    vx=(bx-ax)/dt
    vy=(by-ay)/dt
    length=math.hypot(vx,vy)*sample_dt_s
    if length<=1e-9:
        raise ValueError("Degenerate projected orbit ground speed")
    ux=vx/math.hypot(vx,vy)
    uy=vy/math.hypot(vx,vy)
    half=length/2
    line=LineString([(x-ux*half,y-uy*half),(x+ux*half,y+uy*half)])
    # flat caps model a single rectangular cross-track strip cell.
    return line.buffer(float(width_m)/2,cap_style=2,join_style=2)


def polygon_coverage(regions:dict, tasks:list, lines:list, ground_track:list,
                     sample_dt_s:float)->dict:
    """Union clipped real-generated strip cell footprints by territory.

    Returns plain JSON serializable metrics; use `coverage_geojson` for features.
    """
    from shapely.ops import unary_union
    coverage={}
    line_by_task=defaultdict(list)
    for line in lines:
        line_by_task[line["task"]].append(line)
    collected_by_region=defaultdict(list)
    coverage_by_task={}
    features=[]
    region_caches={}
    for task in tasks:
        if task.get("kind","point")!="strip":
            continue
        target_id=task["region_id"]
        if target_id not in region_caches:
            region_caches[target_id]=_region_projection(
                regions[target_id]["polygon_lat_lon_deg"])
        projector,back,target=region_caches[target_id]
        cells=[]
        source_lines=line_by_task[task["id"]]
        for row in source_lines:
            cell=_footprint_at(
                float(row["t_s"]),float(row["lat_deg"]),float(row["lon_deg"]),
                float(row["swath_width_m"]),sample_dt_s,ground_track,projector)
            clipped=cell.intersection(target)
            if not clipped.is_empty and clipped.area>0:
                cells.append(clipped)
        # Don't count the same footprint more than once within one strip task.
        union=unary_union(cells) if cells else target.intersection(target.buffer(-1e20))
        measured=0.0 if not cells else float(union.area)
        collected_by_region[target_id].extend(cells)
        target_area=float(target.area)
        percent=max(0.,min(100.,100.*measured/target_area))
        coverage_by_task[task["id"]]={
            "task_id":task["id"],
            "region_id":target_id,
            "real_generated_line_count":len(source_lines),
            "region_area_m2":target_area,
            "covered_area_m2":measured,
            "covered_percent":percent,
            "uncovered_area_m2":max(0.,target_area-measured),
            "method":"WGS84_LAEA_union_intersection_sampled_spherical_nadir_FOV",
        }
        if cells:
            from shapely.geometry import mapping
            from shapely.ops import transform
            geo=transform(lambda x,y,z=None: back.transform(x,y),union)
            features.append({"type":"Feature","properties":{
                "task_id":task["id"],"region_id":target_id,
                "covered_area_m2":measured},
                "geometry":mapping(geo)})
    for key,region in regions.items():
        if key not in region_caches:
            region_caches[key]=_region_projection(region["polygon_lat_lon_deg"])
        _,back,target=region_caches[key]
        union=unary_union(collected_by_region[key]) if collected_by_region[key] else None
        covered=0. if union is None else float(target.intersection(union).area)
        base=float(target.area)
        if covered>base+base*1e-8:
            raise AssertionError("Union territory coverage exceeds area")
        coverage[key]={
            "region_id":key,
            "region_area_m2":base,
            "covered_area_m2":max(0.,min(base,covered)),
            "covered_percent":max(0.,min(100.,100.*covered/base)),
            "uncovered_area_m2":max(0.,base-covered),
        }
    return {
        "regions":coverage,
        "task_coverage":coverage_by_task,
        "total_region_area_m2":sum(r["region_area_m2"] for r in coverage.values()),
        "total_covered_area_m2":sum(r["covered_area_m2"] for r in coverage.values()),
        "coverage_geojson":{"type":"FeatureCollection","features":features},
        "method":"WGS84_LAEA; union per task and region; clip cell rectangles; zero overlap double count",
        "limitations":[
            "Geometric estimated coverage from synthetic Basilisk camera data and rectangle cells, not verified pixels",
            "Cross-track width uses flat-surface h*tan(FOV/2) and nadir simplification; no exact ray/ellipsoid optics",
            "UTC/Earth orientation accuracy depends on supplied DUT1 and simplified Basilisk GMST orientation",
            "Tiny footprint positioning errors from camera pointing and spherical Basilisk ground locations remain",
        ],
    }
