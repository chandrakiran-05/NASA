"""Geometry normalisation: GeoJSON Point / Polygon plus a `BBox` extension type.

Internally every request is reduced to a `Region` that each connector can read in the
form it supports (point, bbox, or polygon).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from .errors import InvalidRequest


@dataclass(frozen=True)
class Region:
    kind: str                                   # "point" | "bbox" | "polygon"
    bbox: tuple[float, float, float, float]     # west, south, east, north
    point: tuple[float, float] | None = None    # lon, lat
    polygon: tuple[tuple[float, float], ...] | None = None
    name: str | None = field(default=None, compare=False)

    @property
    def is_point(self) -> bool:
        return self.kind == "point"

    @property
    def centroid(self) -> tuple[float, float]:
        if self.point:
            return self.point
        w, s, e, n = self.bbox
        return ((w + e) / 2.0, (s + n) / 2.0)

    @property
    def area_deg2(self) -> float:
        w, s, e, n = self.bbox
        return max(e - w, 0.0) * max(n - s, 0.0)

    def to_geojson(self) -> dict:
        if self.kind == "point":
            return {"type": "Point", "coordinates": list(self.point)}
        if self.kind == "polygon":
            return {"type": "Polygon", "coordinates": [[list(p) for p in self.polygon]]}
        w, s, e, n = self.bbox
        return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}

    def as_dict(self) -> dict:
        d = {"type": "Point" if self.kind == "point" else ("BBox" if self.kind == "bbox" else "Polygon")}
        if self.kind == "point":
            d["coordinates"] = list(self.point)
        elif self.kind == "bbox":
            d["bbox"] = list(self.bbox)
        else:
            d["coordinates"] = [[list(p) for p in self.polygon]]
        if self.name:
            d["name"] = self.name
        return d

    def key(self) -> str:
        """Stable short hash, used in cache keys and series ids."""
        payload = json.dumps(self.as_dict() | {"name": None}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _check_lonlat(lon: float, lat: float) -> None:
    if not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
        raise InvalidRequest(f"Coordinate out of range: lon={lon}, lat={lat}")


def parse_geometry(g: dict) -> Region:
    """Accept GeoJSON Point, Polygon, Feature wrapper, or {type: BBox, bbox: [w,s,e,n]}."""
    if not isinstance(g, dict) or "type" not in g:
        raise InvalidRequest("geometry must be a GeoJSON object with a 'type'")
    if g["type"] == "Feature":
        return parse_geometry(g.get("geometry") or {})
    t = g["type"]
    name = g.get("name")
    if t == "Point":
        lon, lat = (float(v) for v in g["coordinates"][:2])
        _check_lonlat(lon, lat)
        return Region("point", (lon, lat, lon, lat), point=(lon, lat), name=name)
    if t == "BBox":
        try:
            w, s, e, n = (float(v) for v in g["bbox"])
        except Exception as exc:  # noqa: BLE001
            raise InvalidRequest("BBox needs bbox=[west, south, east, north]") from exc
        _check_lonlat(w, s)
        _check_lonlat(e, n)
        if not (e > w and n > s):
            raise InvalidRequest("BBox must have east > west and north > south (antimeridian crossing unsupported)")
        return Region("bbox", (w, s, e, n), name=name)
    if t == "Polygon":
        ring = g["coordinates"][0]
        pts = tuple((float(p[0]), float(p[1])) for p in ring)
        if len(pts) < 4:
            raise InvalidRequest("Polygon ring needs at least 4 positions (closed)")
        for lon, lat in pts:
            _check_lonlat(lon, lat)
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        return Region("polygon", (min(lons), min(lats), max(lons), max(lats)), polygon=pts, name=name)
    raise InvalidRequest(f"Unsupported geometry type {t!r}; use Point, Polygon or BBox")


def point_buffer(lon: float, lat: float, radius_km: float, name: str | None = None) -> Region:
    """Square bbox of +-radius around a point (used for cities from the gazetteer)."""
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.05))
    return Region(
        "bbox",
        (max(lon - dlon, -180), max(lat - dlat, -90), min(lon + dlon, 180), min(lat + dlat, 90)),
        name=name,
    )


def point_in_polygon(lon: float, lat: float, poly: tuple[tuple[float, float], ...]) -> bool:
    """Ray casting; used to mask gridded pixels for polygon regions."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-300) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside
