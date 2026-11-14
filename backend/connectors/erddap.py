"""NOAA ERDDAP griddap (CoastWatch, PolarWatch, upwell): any gridded dataset named in the catalog.

Catalog fields: erddap_base, dataset_id, erddap_variable, optional erddap_zdim (value of the extra
depth/altitude axis, e.g. 0.0 for ERSST) and erddap_lon360 (dataset longitudes run 0..360).
The time/latitude/longitude axes are read first (.csv0) so every constraint is an index range:
ERDDAP refuses value ranges that start before the first time step or run against a descending axis.
  point: the 3x3 cells around the nearest one; the nearest cell that has data is used, because
         coarse grids (ERSST is 2 deg) put many coastal points on a land cell
  area : the box with a stride that keeps the whole answer under MAX_VALUES numbers, split into time
         chunks; cos(latitude)-weighted mean per time step over the cells that have data (land is NaN)
"""
from __future__ import annotations

import asyncio
import io
import math
from urllib.parse import quote

import numpy as np
import pandas as pd

from ..core.errors import InvalidRequest, UpstreamUnavailable
from ..core.geometry import point_in_polygon
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from .base import Connector, FetchRequest, ProgressFn, _noop
from .opendap import index_range

MAX_VALUES = 200_000        # numbers per area request, all chunks together
CHUNK_VALUES = 50_000       # numbers per HTTP request
MIN_VALID_FRACTION = 0.3    # as gridded.area_mean, but relative to cells that ever have data (land never does)


def parse_griddap_csv(text: str, var: str) -> tuple[pd.DataFrame, str | None]:
    """ERDDAP .csv: column names, a units row, then rows; missing values arrive as NaN."""
    names, units_row = text.split("\n", 2)[:2]
    units = dict(zip(names.strip().split(","), units_row.strip().split(","))).get(var) or None
    df = pd.read_csv(io.StringIO(text), skiprows=[1])
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(None)
    return df, units


class ERDDAPGrid(Connector):
    name = "erddap"

    @staticmethod
    def _url(v: dict, fmt: str, query: str) -> str:
        # httpx leaves [ ] unencoded and some ERDDAP front ends reject them
        return f"{v['erddap_base'].rstrip('/')}/griddap/{v['dataset_id']}.{fmt}?{quote(query, safe=':(),')}"

    async def _axis(self, v: dict, axis: str, use_cache: bool = True) -> list[str]:
        r = await self.http.request("GET", self._url(v, "csv0", f"{axis}[0:1:last]"), use_cache=use_cache)
        return r.text.split()

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        var = v["erddap_variable"]
        await progress(0.02, "Reading the ERDDAP grid axes")
        # time axis not cached: new months must show up
        times = pd.DatetimeIndex(pd.to_datetime(await self._axis(v, "time", use_cache=False), utc=True)
                                 .tz_convert(None))
        lat = np.array(await self._axis(v, "latitude"), float)
        lon = np.array(await self._axis(v, "longitude"), float)
        t_idx = np.where((times >= pd.Timestamp(req.start)) & (times < pd.Timestamp(req.end) + pd.Timedelta(days=1)))[0]
        if not len(t_idx):
            raise UpstreamUnavailable(f"{v['dataset_id']} has no data in {req.start}..{req.end} "
                                      f"(it covers {times[0]:%Y-%m}..{times[-1]:%Y-%m})")
        w, s, e, n = req.region.bbox
        if v.get("erddap_lon360"):
            w, e = w % 360, e % 360
            if w > e:
                raise InvalidRequest("This dataset uses 0..360° longitudes; draw a box that does not cross 0° longitude")
        if req.region.is_point:
            ii, jj = int(np.argmin(np.abs(lat - s))), int(np.argmin(np.abs(lon - w)))
            i0, i1, j0, j1 = max(ii - 1, 0), min(ii + 1, len(lat) - 1), max(jj - 1, 0), min(jj + 1, len(lon) - 1)
            stride = 1
        else:
            (i0, i1), (j0, j1) = index_range(lat, s, n), index_range(lon, w, e)
            budget = max(1, MAX_VALUES // len(t_idx))
            stride = max(1, math.ceil(math.sqrt((i1 - i0 + 1) * (j1 - j0 + 1) / budget)))
        cells = len(range(i0, i1 + 1, stride)) * len(range(j0, j1 + 1, stride))
        step = max(1, CHUNK_VALUES // cells)
        z = f"[({v['erddap_zdim']})]" if v.get("erddap_zdim") is not None else ""
        t0, t1 = int(t_idx[0]), int(t_idx[-1])
        queries = [f"{var}[{a}:1:{min(a + step - 1, t1)}]{z}[{i0}:{stride}:{i1}][{j0}:{stride}:{j1}]"
                   for a in range(t0, t1 + 1, step)]

        sem = asyncio.Semaphore(2)
        state = {"done": 0}

        async def one(q: str):
            async with sem:
                r = await self.http.request("GET", self._url(v, "csv", q))
            state["done"] += 1
            await progress(0.1 + 0.85 * state["done"] / len(queries), f"ERDDAP request {state['done']}/{len(queries)}")
            return r

        resps = await asyncio.gather(*(one(q) for q in queries))
        parsed = [parse_griddap_csv(r.text, var) for r in resps]
        df = pd.concat([p[0] for p in parsed], ignore_index=True)
        if v.get("erddap_lon360"):
            df["longitude"] = (df["longitude"] + 180.0) % 360.0 - 180.0
        cube = df.set_index(["time", "latitude", "longitude"])[var].unstack(["latitude", "longitude"]).sort_index()
        la = cube.columns.get_level_values("latitude").to_numpy(float)
        lo = cube.columns.get_level_values("longitude").to_numpy(float)
        vals = cube.to_numpy(float)
        has = np.isfinite(vals)

        if req.region.is_point:
            plon, plat = req.region.point
            dist = np.hypot(la - plat, (lo - plon) * math.cos(math.radians(plat)))
            dist[~has.any(axis=0)] = np.inf
            k = int(np.argmin(dist))
            if not np.isfinite(dist[k]):
                raise UpstreamUnavailable(f"No {var} values in the grid cells around ({plat}, {plon})",
                                          detail={"hint": "Land cells have no ocean data; move the point offshore."})
            series = vals[:, k]
            note = (f"nearest grid cell with data: lat={la[k]}, lon={lo[k]} "
                    f"(about {dist[k] * 111.2:.0f} km from the point)")
        else:
            inside = np.ones(len(la), bool)
            if req.region.polygon:
                inside = np.array([point_in_polygon(x, y, req.region.polygon) for x, y in zip(lo, la)])
                if not inside.any():          # polygon smaller than one grid cell: keep the nearest cell
                    inside[:] = True
            wts = np.where(inside, np.cos(np.deg2rad(la)), 0.0)
            ok = has & (wts > 0)
            ever = wts[ok.any(axis=0)].sum()
            den = (ok * wts).sum(axis=1)
            num = np.where(ok, vals, 0.0) @ wts
            with np.errstate(invalid="ignore", divide="ignore"):
                series = np.where((den > 0) & (den >= MIN_VALID_FRACTION * ever), num / den, np.nan)
            note = (f"area mean computed locally with cos(latitude) weights over {int(ok.any(axis=0).sum())} grid "
                    f"cells that have data (1 of every {stride} cells along each axis); time steps with less than "
                    f"{MIN_VALID_FRACTION:.0%} of those cells valid are left missing")
        ds = v.get("dataset") or {}
        prov = Provenance(
            source_api="erddap.griddap", variable=var, geometry=req.region.as_dict(),
            dataset_short_name=v["dataset_id"], version=ds.get("version"), doi=ds.get("doi"),
            request_url=self._url(v, "csv", queries[0]), citation=ds.get("citation"),
            notes=[f"ERDDAP server {v['erddap_base']}", f"{len(queries)} request chunk(s)", note],
            from_cache=all(r.from_cache for r in resps))
        return RawSeries(cube.index.to_numpy("datetime64[ns]"), series, v.get("native_resolution", "monthly"), prov,
                         ValueMeta(units=parsed[0][1] or v.get("units")))
