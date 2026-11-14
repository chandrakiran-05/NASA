"""NOAA NCEI station observations.

Primary : NCEI Access Data Service (no token; verified live in the reference doc)
          GET /access/services/data/v1?dataset=global-summary-of-the-month&stations=...&dataTypes=...
Fallback: CDO Web Services v2 (token header; 5 req/s, 10k/day; 1000 rows/request; monthly data in
          10-year windows). CDO /stations is also used to discover stations inside a region.

Area requests average several stations with the climate-anomaly method (each station's
anomalies vs its own monthly climatology are averaged, then the mean climatology is added
back), so stations joining or leaving the network do not create fake trends.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from ..core.auth import cdo_headers
from ..core.errors import CredentialsMissing, InvalidRequest, UpstreamError, UpstreamUnavailable
from ..core.geometry import Region
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from ..timeseries.parsers import parse_cdo_json, parse_ncei_ads_json
from .base import Connector, FetchRequest, ProgressFn, _noop


def _ten_year_windows(start: date, end: date) -> list[tuple[date, date]]:
    out = []
    a = start
    while a <= end:
        b = min(date(a.year + 9, 12, 31), end)
        out.append((a, b))
        a = date(b.year + 1, 1, 1)
    return out


def anomaly_average(series: dict[str, pd.Series]) -> pd.Series:
    if len(series) == 1:
        return next(iter(series.values()))
    df = pd.DataFrame(series)
    month = df.index.month
    clim = df.groupby(month).transform("mean")
    anom = df - clim
    mean_anom = anom.mean(axis=1, skipna=True)
    mean_clim = clim.mean(axis=1, skipna=True)
    out = mean_anom + mean_clim
    out[df.notna().sum(axis=1) == 0] = np.nan
    return out


class NCEIStations(Connector):
    name = "ncei"

    async def find_stations(self, region: Region, datatype: str, start: date, end: date,
                            cdo_dataset: str = "GSOM", limit: int = 25) -> list[dict]:
        """CDO /stations inside the region (point -> +-0.5 deg box), best coverage first."""
        w, s, e, n = region.bbox
        if region.is_point:
            w, s, e, n = w - 0.5, s - 0.5, e + 0.5, n + 0.5
        r = await self.http.request(
            "GET", f"{self.s.cdo_base}/stations", headers=cdo_headers(self.s),
            params={"extent": f"{s},{w},{n},{e}", "datasetid": cdo_dataset, "datatypeid": datatype,
                    "startdate": start.isoformat(), "enddate": end.isoformat(), "limit": 1000,
                    "sortfield": "datacoverage", "sortorder": "desc"})
        res = r.json().get("results", []) or []
        need_years = (end.year - start.year + 1)
        out = []
        for st in res:
            try:
                yrs = (min(pd.Timestamp(st["maxdate"]), pd.Timestamp(end)) -
                       max(pd.Timestamp(st["mindate"]), pd.Timestamp(start))).days / 365.25
            except Exception:  # noqa: BLE001
                yrs = 0
            st["overlap_years"] = max(yrs, 0)
            if region.is_point:
                plon, plat = region.point
                st["distance_km"] = 111.2 * math.hypot(st["latitude"] - plat,
                                                       (st["longitude"] - plon) * math.cos(math.radians(plat)))
            out.append(st)
        out = [st for st in out if st["overlap_years"] >= min(10, need_years * 0.5)]
        key = (lambda x: (x["distance_km"], -x.get("datacoverage", 0))) if region.is_point else \
            (lambda x: (-x["overlap_years"], -x.get("datacoverage", 0)))
        return sorted(out, key=key)[:limit]

    async def _ads(self, dataset: str, stations: list[str], datatype: str, start: date, end: date):
        r = await self.http.request("GET", self.s.ncei_ads_base, params={
            "dataset": dataset, "stations": ",".join(stations), "startDate": start.isoformat(),
            "endDate": end.isoformat(), "dataTypes": datatype, "format": "json", "units": "metric"})
        return r, parse_ncei_ads_json(r.content, datatype)

    async def _cdo(self, dataset: str, station: str, datatype: str, start: date, end: date):
        payloads = []
        sid = station if ":" in station else f"GHCND:{station}"
        for a, b in _ten_year_windows(start, end):
            offset = 1
            while True:
                r = await self.http.request("GET", f"{self.s.cdo_base}/data", headers=cdo_headers(self.s), params={
                    "datasetid": dataset, "stationid": sid, "datatypeid": datatype, "startdate": a.isoformat(),
                    "enddate": b.isoformat(), "units": "metric", "limit": 1000, "offset": offset})
                p = r.json() if r.content.strip() else {}
                payloads.append(p)
                rs = (p.get("metadata") or {}).get("resultset") or {}
                count = int(rs.get("count", 0))
                offset += 1000
                if offset > count:
                    break
        return parse_cdo_json(payloads, datatype)

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        datatype = v["datatype"]
        dataset = v.get("ncei_dataset", "global-summary-of-the-month")
        cdo_ds = v.get("cdo_dataset", "GSOM")
        stations: list[str] = list(req.options.get("stations") or [])
        station_meta: list[dict] = []
        if not stations:
            try:
                await progress(0.05, "Finding weather stations (CDO /stations)")
                found = await self.find_stations(req.region, datatype, req.start, req.end, cdo_ds)
            except CredentialsMissing as exc:
                raise InvalidRequest(
                    "Give station id(s) in options.stations (e.g. USW00094728), or set NOAA_CDO_TOKEN so the "
                    "server can find stations in your region.") from exc
            if not found:
                raise UpstreamUnavailable("No station with a long enough record in this region")
            pick = found[:1] if req.region.is_point else found[: int(req.options.get("max_stations", 8))]
            stations = [st["id"].split(":")[-1] for st in pick]
            station_meta = [{k: st.get(k) for k in ("id", "name", "latitude", "longitude", "mindate", "maxdate",
                                                     "datacoverage", "distance_km")} for st in pick]
        await progress(0.2, f"Downloading {len(stations)} station record(s)")
        per_station: dict[str, pd.Series] = {}
        used_api = "ncei.ads"
        url = None
        try:
            r, (t, val, st_ids) = await self._ads(dataset, stations, datatype, req.start, req.end)
            url = r.url
            df = pd.DataFrame({"t": t, "v": val, "s": st_ids})
            for sid, g in df.groupby("s"):
                per_station[sid] = pd.Series(g["v"].to_numpy(), index=pd.DatetimeIndex(g["t"])).sort_index()
        except UpstreamError:
            used_api = "ncei.cdo_v2"
            for i, sid in enumerate(stations):
                t, val = await self._cdo(cdo_ds, sid, datatype, req.start, req.end)
                per_station[sid] = pd.Series(val, index=pd.DatetimeIndex(t)).sort_index()
                await progress(0.2 + 0.7 * (i + 1) / len(stations), f"CDO station {i + 1}/{len(stations)}")
        per_station = {k: s.groupby(s.index.to_period("M")).mean().to_timestamp() for k, s in per_station.items()
                       if s.notna().any()}
        if not per_station:
            raise UpstreamUnavailable(f"No {datatype} values returned for stations {stations}")
        combined = anomaly_average(per_station)
        prov = Provenance(
            source_api=used_api, variable=datatype, geometry=req.region.as_dict(), dataset_short_name=cdo_ds,
            request_url=(url.split("&startDate")[0] if url else f"{self.s.cdo_base}/data"),
            citation="NOAA NCEI Global Summary of the Month (GSOM)",
            notes=[f"stations: {', '.join(per_station)}"] + (
                ["multi-station climate-anomaly average"] if len(per_station) > 1 else []),
        )
        rs = RawSeries(combined.index.to_numpy("datetime64[ns]"), combined.to_numpy(float), "monthly", prov,
                       ValueMeta(units=v.get("units")))
        rs.provenance.notes.append(f"station_meta={station_meta}" if station_meta else "stations given by user")
        return rs
