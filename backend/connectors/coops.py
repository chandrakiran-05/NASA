"""NOAA CO-OPS tide gauges: monthly mean sea level (Tides & Currents data API, product=monthly_mean).

GET {API}?product=monthly_mean&station=<id>&datum=MSL&units=metric&time_zone=gmt&format=json&begin_date=&end_date=
-> {"metadata": {id, name, lat, lon}, "data": [{"year", "month", "MSL", ..., "inferred"}]}; MSL in metres
relative to the station's MSL tidal datum. The API refuses more than 73 000 days per request, so
requests are split into 100-year windows.
Station: options.station_id, else the nearest tidal water-level station (CO-OPS metadata API) within
MAX_DEG of the point or box centre. Months whose "inferred" field is not 0 (some values inferred, i.e.
not directly measured; live values range 0..13, not just the documented 0/1) are left missing.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from ..core.errors import InvalidRequest, UpstreamUnavailable
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from .base import Connector, FetchRequest, ProgressFn, _noop

API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATIONS = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
MAX_DEG = 1.0
WINDOW_YEARS = 100


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    out, a = [], start
    while a <= end:
        b = min(date(a.year + WINDOW_YEARS - 1, 12, 31), end)
        out.append((a, b))
        a = date(b.year + 1, 1, 1)
    return out


class NOAACoops(Connector):
    name = "noaa_coops"
    supports_area = False

    async def nearest_station(self, lon: float, lat: float) -> dict:
        r = await self.http.request("GET", STATIONS, params={"type": "waterlevels"})
        best, best_d = None, MAX_DEG
        for st in r.json().get("stations", []):
            if not st.get("tidal"):           # Great Lakes gauges have no MSL tidal datum
                continue
            d = math.hypot(st["lat"] - lat, (st["lng"] - lon) * math.cos(math.radians(lat)))
            if d <= best_d:
                best, best_d = st, d
        if best is None:
            raise InvalidRequest(f"No NOAA tide gauge within about {MAX_DEG:.0f}° ({MAX_DEG * 111:.0f} km) of this "
                                 "place. CO-OPS gauges are on US coasts and islands; pick a point next to one, or give "
                                 "options.station_id.")
        return {**best, "distance_km": round(best_d * 111.2, 1)}

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        lon, lat = req.region.centroid
        sid = req.options.get("station_id")
        picked = None
        if not sid:
            await progress(0.05, "Finding the nearest tide gauge (CO-OPS metadata API)")
            picked = await self.nearest_station(lon, lat)
            sid = picked["id"]
        rows, meta, urls, cached = [], {}, [], True
        wins = _windows(req.start, req.end)
        for k, (a, b) in enumerate(wins):
            r = await self.http.request("GET", API, params={
                "product": "monthly_mean", "station": sid, "datum": "MSL", "units": "metric", "time_zone": "gmt",
                "format": "json", "begin_date": a.strftime("%Y%m%d"), "end_date": b.strftime("%Y%m%d"),
                "application": "etd"})
            d = r.json()
            if "error" in d:          # CO-OPS answers 200 with an error object (e.g. no data in this window)
                if len(wins) == 1:
                    raise UpstreamUnavailable(f"CO-OPS station {sid}: {d['error'].get('message', '').strip()}")
                continue
            meta = d.get("metadata") or meta
            rows += d.get("data") or []
            urls.append(r.url)
            cached = cached and r.from_cache
            await progress(0.1 + 0.85 * (k + 1) / len(wins), f"CO-OPS window {k + 1}/{len(wins)}")
        if not rows:
            raise UpstreamUnavailable(f"CO-OPS station {sid} has no monthly mean sea level in {req.start}..{req.end}")
        df = pd.DataFrame(rows)
        t = pd.to_datetime({"year": df["year"].astype(int), "month": df["month"].astype(int), "day": 1})
        val = pd.to_numeric(df["MSL"], errors="coerce").to_numpy(float)       # "" -> NaN
        observed = df.get("inferred", pd.Series("0", index=df.index)).astype(str).str.strip().to_numpy() == "0"
        ds = v.get("dataset") or {}
        name = meta.get("name") or (picked or {}).get("name")
        prov = Provenance(
            source_api="noaa_coops.monthly_mean", variable="MSL", geometry=req.region.as_dict(),
            dataset_short_name=ds.get("short_name", "CO-OPS monthly_mean"), version=ds.get("version"),
            doi=ds.get("doi"), request_url=urls[0].split("&begin_date")[0] if urls else API,
            citation=ds.get("citation"),
            notes=[f"tide gauge {sid} {name} (lat {meta.get('lat')}, lon {meta.get('lon')})"
                   + (f", {picked['distance_km']} km from the requested place" if picked else ", chosen by the user"),
                   "monthly mean sea level relative to the station's MSL tidal datum; includes vertical land motion "
                   "(relative sea level)",
                   f"{int((~observed).sum())} month(s) with a non-zero CO-OPS 'inferred' field (values not directly "
                   "measured) left missing"],
            from_cache=cached)
        return RawSeries(t.to_numpy("datetime64[ns]"), val, "monthly", prov, ValueMeta(units=v.get("units", "m")),
                         qc_pass=observed)
