"""Stage 1 "Scan": a cheap per-cell trend sweep over keyless NOAA ERDDAP grids.

Re-uses the ERDDAP connector's `fetch_cube` (same stride budget and chunking as the trend map) and
`insights.cube.cube_trends` (per-cell OLS AR(1) + Mann-Kendall, BH-FDR field significance). The sweep is
exploratory: it only nominates places. Every nominated place is then re-built as a proper monthly series
and must pass the active-trend checks and BEAST before it can become a finding.
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pandas as pd
from starlette.concurrency import run_in_threadpool

from ..connectors.base import FetchRequest
from ..core.geometry import Region
from ..insights.cube import cube_trends

# criterion -> keyless gridded ERDDAP variable used for the sweep (catalog ids)
SWEEP_VARIABLES = {
    "temperature": "global_t2m",
    "precipitation": "global_precip_chirps",   # CHIRPS on CoastWatch; R2 prate mirror on upwell 404s
    "soil_moisture": "global_soil_moisture",
    "sea_surface_temperature": "sst",
    "chlorophyll": "modis_chlorophyll",
}
OCEAN_CRITERIA = ("sea_surface_temperature", "chlorophyll")
DEFAULT_GLOBAL_CRITERIA = ["temperature", "precipitation", "soil_moisture", "sea_surface_temperature"]
GLOBAL_BOX = (-180.0, -60.0, 180.0, 72.0)
MIN_SEPARATION_DEG = 15.0           # nominated cells of one variable must be this far apart (great-circle-ish)
MIN_HALF_BOX_DEG = 2.5
MAX_HALF_BOX_DEG = 5.0
SWEEP_NOTE = ("Exploratory sweep: each grid cell is tested on its own (field significance corrected with "
              "Benjamini-Hochberg). A cell only nominates a place; it is not a finding until the place passes the "
              "active-trend checks and BEAST.")


def _split_for_lon360(box: tuple, lon360: bool) -> list[tuple]:
    """ERDDAP grids stored 0..360 cannot take a box crossing 0 deg longitude: split it there."""
    w, s, e, n = box
    if lon360 and w < 0 < e:
        return [(w, s, -0.01, n), (0.0, s, e, n)]
    if lon360 and w < 0 and e <= 0:
        return [(w, s, min(e, -0.01), n)]
    return [box]


async def sweep_variable(st, criterion: str, variable_id: str, box: tuple, start, end, *, alpha: float = 0.05,
                         k: int = 3) -> dict:
    """-> {status, variable_id, criterion, cells[], grids[], units, provenance, plain_language}; never raises
    for an upstream failure (status 'failed' with the reason instead)."""
    v = st.catalog.get(variable_id)
    out = {"criterion": criterion, "variable_id": variable_id, "name": v["name"], "status": "ok",
           "note": SWEEP_NOTE, "grids": [], "cells": []}
    cells: list[dict] = []
    fails = []
    for part in _split_for_lon360(box, bool(v.get("erddap_lon360"))):
        try:
            times, cube, lat, lon, units, prov = await st.ts.connectors["erddap"].fetch_cube(
                FetchRequest(v, Region("bbox", part), start, end))
        except Exception as exc:  # noqa: BLE001 - a dead grid is reported, never sinks the job
            fails.append(getattr(exc, "message", str(exc))[:300])
            continue
        months = pd.DatetimeIndex(times).month.to_numpy()
        res = await run_in_threadpool(cube_trends, cube, months, lat, lon, alpha=alpha)
        spacing = float(np.median(np.diff(lat))) if len(lat) > 1 else 2.5
        out["units"] = units
        out["provenance"] = prov.to_dict()
        out["period"] = [str(pd.Timestamp(times[0]).date()), str(pd.Timestamp(times[-1]).date())]
        out["grids"].append({"lat": res["lat"], "lon": res["lon"], "slope_per_decade": res["slope_per_decade"],
                             "significant": res["significant"],
                             "area_fraction_rising": res["area_fraction_rising"],
                             "area_fraction_falling": res["area_fraction_falling"],
                             "plain_language": res["plain_language"]})
        for i, la in enumerate(res["lat"]):
            for j, lo in enumerate(res["lon"]):
                if not res["significant"][i][j]:
                    continue
                po, pm, sl = res["p_ols_adj"][i][j], res["p_mk"][i][j], res["slope_per_decade"][i][j]
                if po is None or pm is None or sl is None:
                    continue
                cells.append({"lat": la, "lon": lo, "slope_per_decade": sl, "p": max(po, pm),
                              "spacing_deg": abs(spacing)})
    if not out["grids"]:
        return {**out, "status": "failed", "reason": "; ".join(fails) or "no data",
                "plain_language": f"The {v['name']} grid could not be read, so it was not swept."}
    if fails:
        out["partial_failures"] = fails
    out["n_significant_cells"] = len(cells)
    out["cells"] = pick_cells(cells, k)
    out["plain_language"] = (f"{v['name']}: {len(cells)} grid cells show a significant trend after the field "
                             f"correction; the {len(out['cells'])} strongest, well-separated cells were nominated.")
    return out


def pick_cells(cells: list[dict], k: int, min_sep: float = MIN_SEPARATION_DEG) -> list[dict]:
    """Strongest evidence first (smallest combined p, then largest |slope|), at least `min_sep` degrees apart."""
    chosen: list[dict] = []
    for c in sorted(cells, key=lambda c: (c["p"], -abs(c["slope_per_decade"]))):
        if all(_dist(c, o) >= min_sep for o in chosen):
            chosen.append(c)
        if len(chosen) >= k:
            break
    return chosen


def _dist(a: dict, b: dict) -> float:
    dlon = abs(a["lon"] - b["lon"]) % 360
    dlon = min(dlon, 360 - dlon) * math.cos(math.radians((a["lat"] + b["lat"]) / 2))
    return math.hypot(a["lat"] - b["lat"], dlon)


def cell_region(cell: dict, ocean: bool = False) -> Region:
    h = float(np.clip(cell.get("spacing_deg", 2.5) / 2, MIN_HALF_BOX_DEG, MAX_HALF_BOX_DEG))
    lo, la = cell["lon"], cell["lat"]
    box = (max(lo - h, -180.0), max(la - h, -90.0), min(lo + h, 180.0), min(la + h, 90.0))
    name = place_name(lo, la, ocean=ocean)
    return Region("bbox", tuple(round(x, 3) for x in box), name=name)


@lru_cache(maxsize=1)
def _named_boxes() -> list[tuple[float, str, tuple, str]]:
    from ..ai import gazetteer
    out = []
    seen = set()
    for rec in gazetteer._index().values():
        b = rec.get("bbox")
        if not b or rec["name"] in seen:
            continue
        seen.add(rec["name"])
        area = max(b[2] - b[0], 0) * max(b[3] - b[1], 0)
        if area >= 4.0:                               # skip lakes/cities smaller than a sweep box
            out.append((area, rec["name"], tuple(b), rec.get("kind") or "land"))
    out.sort()
    return out


def place_name(lon: float, lat: float, ocean: bool = False) -> str:
    """Smallest named (approximate) region box from the offline gazetteer that contains the point; for ocean
    variables, sea and ocean boxes are tried first."""
    boxes = _named_boxes()
    if ocean:
        boxes = [b for b in boxes if b[3] == "ocean"] + [b for b in boxes if b[3] != "ocean"]
    for _area, name, (w, s, e, n), _kind in boxes:
        if w <= lon <= e and s <= lat <= n and name not in ("Tropics",):
            return f"{name} (near {abs(lat):.1f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}°{'E' if lon >= 0 else 'W'})"
    return f"grid box at {abs(lat):.1f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}°{'E' if lon >= 0 else 'W'}"


def literature_place(name: str | None) -> str | None:
    """Short place words for literature search and matching: 'Amazon Basin (near 3.0S, 60.0W)' -> 'Amazon'."""
    if not name or name.startswith("grid box"):
        return None
    base = name.split(" (")[0].strip()
    words = base.split()
    while len(words) > 1 and words[-1].lower() in ("basin", "region"):
        words = words[:-1]
    return " ".join(words)
