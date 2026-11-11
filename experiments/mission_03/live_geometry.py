"""Pure-Python directional nadir footprint/territory intersection.

No Shapely, pyproj, NumPy or other native geodesy calls are performed during
Basilisk SysModel.UpdateState. Non-convex polygons are triangulated once and
the oriented rectangular camera cell is intersected with each triangle.
This permission geometry is a WGS84 local tangent approximation; the
postflight WGS84/LAEA Shapely area remains the authoritative science metric.
"""
from __future__ import annotations
import math

_A = 6378137.0
_E2 = (1.0 / 298.257223563) * (2.0 - 1.0 / 298.257223563)

def _cross(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])

def _area(poly):
    return sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1]))/2.0

def _triangle_contains(a,b,c,p):
    return _cross(a,b,p)>=-1e-9 and _cross(b,c,p)>=-1e-9 and _cross(c,a,p)>=-1e-9

def _triangulate(ring):
    """Simple non-self-intersecting polygon, no holes, CCW triangles."""
    polygon=list(ring)
    if _area(polygon)<0: polygon.reverse()
    if len(polygon)<3 or _area(polygon)<=0:
        raise ValueError("Degenerate territory polygon")
    output=[]
    while len(polygon)>3:
        ear=False
        for i in range(len(polygon)):
            a=polygon[i-1];b=polygon[i];c=polygon[(i+1)%len(polygon)]
            if _cross(a,b,c)<=1e-8: continue
            if any(_triangle_contains(a,b,c,p) for j,p in enumerate(polygon)
                   if j not in ((i-1)%len(polygon),i,(i+1)%len(polygon))):
                continue
            output.append((a,b,c))
            del polygon[i]
            ear=True
            break
        if not ear:
            raise ValueError("Non-simple or degenerate territory polygon")
    if _cross(*polygon)<=0:
        raise ValueError("Degenerate final polygon triangle")
    output.append(tuple(polygon))
    return output

def _clip_ccw(subject, a, b):
    if not subject: return []
    result=[]
    previous=subject[-1]
    prev_side=_cross(a,b,previous)
    for point in subject:
        current_side=_cross(a,b,point)
        cur_in=current_side>=-1e-9
        prev_in=prev_side>=-1e-9
        if cur_in!=prev_in:
            diff=prev_side-current_side
            if abs(diff)>1e-20:
                q=prev_side/diff
                result.append((
                    previous[0]+q*(point[0]-previous[0]),
                    previous[1]+q*(point[1]-previous[1])))
        if cur_in: result.append(point)
        previous=point
        prev_side=current_side
    return result

class LiveStripGeometry:
    """Geometrically conservative rectangle/territory overlap during dynamics."""

    def __init__(self,regions):
        self._regions={}
        for region_id,reg in regions.items():
            polygon=reg["polygon_lat_lon_deg"]
            lat0=sum(float(p[0]) for p in polygon)/len(polygon)
            lon0=sum(float(p[1]) for p in polygon)/len(polygon)
            phi=math.radians(lat0)
            den=1-_E2*math.sin(phi)**2
            metres_lat=_A*(1-_E2)/(den**1.5)
            metres_lon=_A*math.cos(phi)/math.sqrt(den)
            def proj(lat,lon):
                dlon=(float(lon)-lon0+180)%360-180
                return (math.radians(dlon)*metres_lon,
                        math.radians(float(lat)-lat0)*metres_lat)
            planar=[proj(lat,lon) for lat,lon in polygon]
            self._regions[region_id]=(lat0,lon0,metres_lat,metres_lon,_triangulate(planar))

    def cell_overlap_m2(self,region_id,previous_fix,now_fix,width_m,*,predict_next):
        if previous_fix is None or now_fix is None: return 0.0
        if not math.isfinite(float(width_m)) or width_m<=0:
            raise ValueError("Invalid swath width")
        lat0,lon0,metres_lat,metres_lon,triangles=self._regions[region_id]
        def proj(fix):
            return (math.radians((float(fix[1])-lon0+180)%360-180)*metres_lon,
                    math.radians(float(fix[0])-lat0)*metres_lat)
        px,py=proj(previous_fix);nx,ny=proj(now_fix)
        dx=nx-px;dy=ny-py
        length=math.hypot(dx,dy)
        if length<1e-8 or not math.isfinite(length): return 0.0
        ux,uy=dx/length,dy/length
        vx,vy=-uy,ux
        cx=nx+(dx if predict_next else 0.0)
        cy=ny+(dy if predict_next else 0.0)
        half_l=length/2;half_w=width_m/2
        def corner(a,b):
            return (cx+a*ux*half_l+b*vx*half_w,
                    cy+a*uy*half_l+b*vy*half_w)
        square=[corner(-1,-1),corner(1,-1),corner(1,1),corner(-1,1)]
        area=0.0
        for triangle in triangles:
            clipped=list(triangle)
            for a,b in zip(square,square[1:]+square[:1]):
                clipped=_clip_ccw(clipped,a,b)
                if not clipped:break
            if len(clipped)>=3:area+=abs(_area(clipped))
        return area
