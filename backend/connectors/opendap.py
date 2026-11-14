"""Cloud OPeNDAP fallback for variables Giovanni does not serve (or is in outage for),
and the data source for per-pixel trend maps.

URL pattern (reference doc §4):
  https://opendap.earthdata.nasa.gov/collections/<concept-id>/granules/<ShortName>.<ver>%3A<file>.dap.nc4?dap4.ce=/VAR
One request per granule, so only MONTHLY collections are used (M2TMNX*, GLDAS_M, IMERG M),
subset spatially with a DAP4 hyperslab:
  1. CMR granule list for the period
  2. first granule: DMR (dimension order of VAR) + lat/lon coordinate arrays  (cached)
  3. every granule: VAR[time][lat i0:i1][lon j0:j1] for the region only     (cached, 6 in parallel)
  4. local cos(lat)-weighted mean (polygon-masked), nearest cell, or the whole cube
"""
from __future__ import annotations

import asyncio
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote

import httpx
import numpy as np
import pandas as pd
import xarray as xr

from ..core.auth import edl_bearer_headers
from ..core.errors import CredentialsMissing, InvalidRequest, UpstreamError, UpstreamUnavailable
from ..timeseries.gridded import _region_mask
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from .base import Connector, FetchRequest, ProgressFn, _noop
from .cmr import CMR

LAT_NAMES = ("lat", "latitude", "Latitude", "YDim")
LON_NAMES = ("lon", "longitude", "Longitude", "XDim")
MAX_CUBE_CELLS = 250_000


def _is_lat(d: str) -> bool:
    return d in LAT_NAMES or d.lower().startswith("lat")


def _is_lon(d: str) -> bool:
    return d in LON_NAMES or d.lower().startswith("lon")


def parse_dmr_dims(xml_text: str, var: str) -> list[str]:
    root = ET.fromstring(xml_text)
    for el in root.iter():
        if el.attrib.get("name") == var and el.tag.split("}")[-1] not in ("Dimension", "Attribute", "Dim"):
            dims = [d.attrib.get("name", "").lstrip("/") for d in el if d.tag.split("}")[-1] == "Dim"]
            if dims:
                return dims
    raise UpstreamError(f"Variable {var} not found in DMR")


def index_range(coord: np.ndarray, lo: float, hi: float) -> tuple[int, int]:
    """Smallest contiguous index range covering [lo, hi] (at least the nearest cell)."""
    c = np.asarray(coord, float)
    sel = np.where((c >= lo) & (c <= hi))[0]
    if len(sel) == 0:
        i = int(np.argmin(np.abs(c - (lo + hi) / 2)))
        return i, i
    return int(sel.min()), int(sel.max())


@dataclass
class _Ctx:
    cid: str
    var: str
    grans: list[dict]
    first_url: str
    ce: str
    sub_lat: np.ndarray
    sub_lon: np.ndarray
    i0: int
    i1: int
    j0: int
    j1: int


class OpendapMonthly(Connector):
    name = "cloud_opendap"

    def __init__(self, settings, http):
        super().__init__(settings, http)
        self.cmr = CMR(settings.cmr_base, http)

    def _auth_kwargs(self) -> dict:
        try:
            return {"headers": edl_bearer_headers(self.s)}   # same token path as Giovanni (incl. username/password)
        except CredentialsMissing:
            pass
        try:
            return {"auth": httpx.NetRCAuth()}
        except Exception as exc:  # noqa: BLE001
            raise CredentialsMissing("Cloud OPeNDAP needs EARTHDATA_TOKEN, EARTHDATA_USERNAME/PASSWORD or ~/.netrc") from exc

    def granule_url(self, concept_id: str, title: str) -> str:
        return f"{self.s.opendap_base}/collections/{concept_id}/granules/{quote(title, safe='')}"

    async def _get(self, url: str, ce: str | None = None):
        kw = self._auth_kwargs()
        params = {"dap4.ce": ce} if ce else None
        return await self.http.request("GET", url, params=params, headers=kw.get("headers"), auth=kw.get("auth"))

    async def _prepare(self, v: dict, req: FetchRequest, progress: ProgressFn) -> _Ctx:
        fb = v.get("fallback")
        if not fb or not fb.get("concept_id"):
            raise UpstreamUnavailable(f"No OPeNDAP monthly collection configured for {v['id']}")
        cid, var = fb["concept_id"], fb["variable"]
        await progress(0.02, "Listing granules in CMR")
        grans = await self.cmr.granules(cid, req.start, req.end)
        if not grans:
            raise UpstreamUnavailable(f"CMR returned no granules for {cid} in {req.start}..{req.end}")
        first = self.granule_url(cid, grans[0]["title"])
        dmr = await self._get(first + ".dmr.xml")
        dims = parse_dmr_dims(dmr.text, var)
        coords = await self._get(first + ".dap.nc4", ce=";".join(f"/{d}" for d in dims if d.lower() != "time"))
        cds = xr.open_dataset(io.BytesIO(coords.content), engine="h5netcdf")
        lat_name = next(d for d in dims if _is_lat(d))
        lon_name = next(d for d in dims if _is_lon(d))
        lat, lon = cds[lat_name].values, cds[lon_name].values
        w, s, e, n = req.region.bbox
        i0, i1 = index_range(lat, s, n)
        j0, j1 = index_range(lon, w, e)
        hyper = "".join(f"[{i0}:1:{i1}]" if d == lat_name else f"[{j0}:1:{j1}]" if d == lon_name else "[0:1:0]"
                        for d in dims)
        return _Ctx(cid, var, grans, first, f"/{var}{hyper}", lat[i0:i1 + 1], lon[j0:j1 + 1], i0, i1, j0, j1)

    async def _grids(self, ctx: _Ctx, progress: ProgressFn) -> tuple[list[np.ndarray], str | None, bool]:
        sem = asyncio.Semaphore(6)
        state = {"done": 0, "cached": True}

        async def one(g: dict):
            async with sem:
                r = await self._get(self.granule_url(ctx.cid, g["title"]) + ".dap.nc4", ce=ctx.ce)
            state["cached"] = state["cached"] and r.from_cache
            ds = xr.open_dataset(io.BytesIO(r.content), engine="h5netcdf", mask_and_scale=True)
            da = ds[ctx.var] if ctx.var in ds.data_vars else ds[next(iter(ds.data_vars))]
            order = list(da.dims)
            lat_ax = next(i for i, d in enumerate(order) if _is_lat(d))
            lon_ax = next(i for i, d in enumerate(order) if _is_lon(d))
            # (lat, lon) regardless of source order (IMERG is time, lon, lat)
            arr = np.moveaxis(da.values.astype(float), (lat_ax, lon_ax), (-2, -1))
            arr = arr.reshape(-1, len(ctx.sub_lat), len(ctx.sub_lon))[0]
            state["done"] += 1
            if state["done"] % 10 == 0 or state["done"] == len(ctx.grans):
                await progress(0.1 + 0.85 * state["done"] / len(ctx.grans),
                               f"OPeNDAP granule {state['done']}/{len(ctx.grans)}")
            return arr, da.attrs.get("units")

        res = await asyncio.gather(*(one(g) for g in ctx.grans))
        units = next((u for _, u in res if u), None)
        return [a for a, _ in res], units, state["cached"]

    def _times(self, ctx: _Ctx) -> np.ndarray:
        return pd.to_datetime([g["time_start"] for g in ctx.grans], utc=True).tz_convert(None).to_numpy("datetime64[ns]")

    def _prov(self, v: dict, req: FetchRequest, ctx: _Ctx, cached: bool, extra: str) -> Provenance:
        fb = v["fallback"]
        return Provenance(
            source_api=self.name, variable=ctx.var, geometry=req.region.as_dict(),
            dataset_short_name=fb.get("short_name"), version=fb.get("version"), concept_id=ctx.cid,
            request_url=ctx.first_url + ".dap.nc4?dap4.ce=" + ctx.ce, doi=(v.get("dataset") or {}).get("doi"),
            notes=[f"{len(ctx.grans)} granules", f"grid subset lat[{ctx.i0}:{ctx.i1}] lon[{ctx.j0}:{ctx.j1}]", extra],
            from_cache=cached)

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        ctx = await self._prepare(v, req, progress)
        grids, units, cached = await self._grids(ctx, progress)
        if req.region.is_point:
            plon, plat = req.region.point
            ii = int(np.argmin(np.abs(ctx.sub_lat - plat)))
            jj = int(np.argmin(np.abs(ctx.sub_lon - plon)))
            vals = np.array([g[ii, jj] for g in grids], float)
            extra = "nearest grid cell"
        else:
            mask = _region_mask(ctx.sub_lat, ctx.sub_lon, req.region)
            if not mask.any():                  # box smaller than one cell: use the nearest cell(s)
                mask[:] = True
            w = np.where(mask, np.cos(np.deg2rad(ctx.sub_lat))[:, None] * np.ones((1, len(ctx.sub_lon))), 0.0)
            vals = []
            for g in grids:
                ok = np.isfinite(g) & (w > 0)
                den = w[ok].sum()
                vals.append(float((g[ok] * w[ok]).sum() / den) if den > 0 else np.nan)
            vals = np.array(vals, float)
            extra = "area mean computed locally with cos(latitude) weights"
        return RawSeries(self._times(ctx), vals, v["fallback"].get("resolution", "monthly"),
                         self._prov(v, req, ctx, cached, extra), ValueMeta(units=units or v.get("units")))

    async def fetch_cube(self, req: FetchRequest, progress: ProgressFn = _noop):
        v = req.variable
        if req.region.is_point:
            raise InvalidRequest("Trend maps need an area (bbox or polygon)")
        ctx = await self._prepare(v, req, progress)
        cells = len(ctx.sub_lat) * len(ctx.sub_lon)
        if cells * len(ctx.grans) > MAX_CUBE_CELLS * 12:
            raise InvalidRequest(f"Region too large for a trend map ({cells} grid cells); draw a smaller box")
        grids, units, cached = await self._grids(ctx, progress)
        cube = np.stack(grids)
        mask = _region_mask(ctx.sub_lat, ctx.sub_lon, req.region)
        if mask.any():                          # box smaller than one cell: keep the nearest cell(s)
            cube[:, ~mask] = np.nan
        prov = self._prov(v, req, ctx, cached, "per-pixel cube for trend map")
        return self._times(ctx), cube, ctx.sub_lat, ctx.sub_lon, units or v.get("units"), prov
