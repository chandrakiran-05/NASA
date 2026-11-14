"""NSIDC Sea Ice Index (G02135, version 4.0): monthly sea-ice extent of a whole hemisphere.

One CSV per calendar month holding every year:
  https://noaadata.apps.nsidc.org/NOAA/G02135/north/monthly/data/N_01_extent_v4.0.csv ... N_12_...
  (south: /south/ and S_). Columns: year, mo, source_dataset, region, extent, area (10^6 km^2); -9999 = no data.
Extent is a hemisphere-wide number, so the region only chooses the hemisphere (sign of its centroid latitude).
"""
from __future__ import annotations

import asyncio
import io

import numpy as np
import pandas as pd

from ..core.errors import InvalidRequest, UpstreamUnavailable
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from .base import Connector, FetchRequest, ProgressFn, _noop

BASE = "https://noaadata.apps.nsidc.org/NOAA/G02135"
MISSING = -9999.0
MIN_ABS_LAT = 40.0


def parse_sea_ice_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    return df


class NSIDCSeaIce(Connector):
    name = "nsidc_seaice"

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        lat = req.region.centroid[1]
        if abs(lat) < MIN_ABS_LAT:
            raise InvalidRequest("Sea-ice extent is a whole-hemisphere number for the polar oceans: put the point or "
                                 f"the centre of the box poleward of {MIN_ABS_LAT:.0f}°N or {MIN_ABS_LAT:.0f}°S")
        hemi, h, label = ("north", "N", "Northern") if lat > 0 else ("south", "S", "Southern")
        urls = [f"{BASE}/{hemi}/monthly/data/{h}_{m:02d}_extent_v4.0.csv" for m in range(1, 13)]
        await progress(0.1, f"Downloading the 12 monthly {label} Hemisphere files")
        resps = await asyncio.gather(*(self.http.request("GET", u) for u in urls))
        df = pd.concat([parse_sea_ice_csv(r.text) for r in resps], ignore_index=True)
        df["t"] = pd.to_datetime({"year": df["year"], "month": df["mo"], "day": 1})
        df = df[(df["t"] >= pd.Timestamp(req.start)) & (df["t"] <= pd.Timestamp(req.end))].sort_values("t")
        if df.empty:
            raise UpstreamUnavailable(f"Sea Ice Index has no {label} Hemisphere months in {req.start}..{req.end}")
        val = df["extent"].to_numpy(float, copy=True)
        val[val == MISSING] = np.nan
        src = df[df["source_dataset"].astype(str) != str(int(MISSING))].groupby("source_dataset")["year"].agg(["min", "max"])
        ds = v.get("dataset") or {}
        prov = Provenance(
            source_api="nsidc.sea_ice_index", variable="extent", geometry=req.region.as_dict(),
            dataset_short_name=ds.get("short_name", "G02135"), version=ds.get("version", "4.0"), doi=ds.get("doi"),
            request_url=urls[0], citation=ds.get("citation"),
            notes=[f"{label} Hemisphere total sea-ice extent: a hemisphere-wide value, not a value for the drawn "
                   "point or box",
                   "input products: " + ", ".join(f"{k} ({a}-{b})" for k, (a, b) in src.iterrows()),
                   f"{int(np.isnan(val).sum())} month(s) marked -9999 (no data) left missing"],
            from_cache=all(r.from_cache for r in resps))
        return RawSeries(df["t"].to_numpy("datetime64[ns]"), val, "monthly", prov,
                         ValueMeta(units=v.get("units")))
