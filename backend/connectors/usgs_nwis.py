"""USGS NWIS daily values, the main US source behind CUAHSI HIS (verified live 2026-11-14).

Primary : legacy WaterServices dv JSON, which is CUAHSI WaterML 1.1 as JSON
          GET https://waterservices.usgs.gov/nwis/dv/?format=json&sites=..&parameterCd=..&startDT=..&endDT=..
Fallback: USGS Water Data OGC API (USGS is retiring the legacy service)
          GET https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items?monitoring_location_id=USGS-..
Sites   : NWIS site service (RDB) inside a box. Point -> nearest gauge within 0.25 deg (0.5 deg once),
          area -> largest drainage area (the most downstream gauge). options.site_id overrides discovery.
"""
from __future__ import annotations

import html
import json
import math

import numpy as np

from ..core.errors import UpstreamError, UpstreamUnavailable
from ..core.geometry import Region
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from .base import Connector, FetchRequest, ProgressFn, _noop

NWIS = "https://waterservices.usgs.gov/nwis"
OGC_DAILY = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items"
NWIS_DOI = "10.5066/F7P55KJN"
# USGS codes that replace a value (ice, equipment, discontinued, seasonal, maintenance, backwater, flood
# damage, rating in development, partial record, test failed, unavailable); OGC API spells some in full
NO_VALUE_CODES = {"ice", "eqp", "equip", "dis", "ssn", "mnt", "bkw", "fld", "rat", "pr", "tst", "***", "--"}


def parse_rdb(text: str) -> list[dict]:
    """USGS RDB: '#' comments, a header row, a column-format row, then tab-separated rows."""
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 2:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[2:]]


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return math.nan


def _flagged(quals) -> bool:
    return any(str(q).lower() in NO_VALUE_CODES for q in quals or [])


def parse_nwis_dv(payload) -> list[dict]:
    """One candidate per (parameter, statistic, method) block of a WaterML 1.1 JSON response."""
    out = []
    for ts in json.loads(payload)["value"]["timeSeries"]:
        _, site, param, stat = ts["name"].split(":")
        var, src = ts["variable"], ts["sourceInfo"]
        geo = src["geoLocation"]["geogLocation"]
        for block in ts["values"]:
            rows = block["value"]
            out.append({
                "site": site, "param": param, "stat": stat, "units": var["unit"]["unitCode"],
                "variable": html.unescape(var["variableName"]), "nodata": var.get("noDataValue"),
                "name": src["siteName"], "lat": geo["latitude"], "lon": geo["longitude"],
                "t": [r["dateTime"][:10] for r in rows], "v": [_num(r["value"]) for r in rows],
                "ok": [not _flagged(r.get("qualifiers")) for r in rows],
                "provisional": sum("P" in r.get("qualifiers", []) for r in rows)})
    return out


def parse_ogc_daily(features: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for f in features:
        p = f["properties"]
        g = groups.setdefault((p["parameter_code"], p["statistic_id"]), {
            "param": p["parameter_code"], "stat": p["statistic_id"], "units": p.get("unit_of_measure"),
            "variable": p["parameter_code"], "nodata": None, "t": [], "v": [], "ok": [], "provisional": 0})
        g["t"].append(p["time"][:10])
        g["v"].append(_num(p["value"]))
        g["ok"].append(not _flagged(p.get("qualifier")))
        g["provisional"] += p.get("approval_status") == "Provisional"
    return list(groups.values())


def _n_valid(c: dict) -> int:
    v = np.asarray(c["v"], float)
    good = np.isfinite(v) & np.asarray(c["ok"], bool)
    if c["nodata"] is not None:
        good &= ~np.isclose(v, c["nodata"])
    return int(good.sum())


def pick_series(cands: list[dict], params: list[str]) -> dict:
    """First parameter in catalog order, then the daily mean (00003), then the longest record."""
    good = [c for c in cands if _n_valid(c)]
    if not good:
        raise UpstreamUnavailable(f"USGS returned no valid daily values for parameter(s) {', '.join(params)}")
    return min(good, key=lambda c: (params.index(c["param"]) if c["param"] in params else len(params),
                                    c["stat"] != "00003", -_n_valid(c)))


def _dist_km(site: dict, lon: float, lat: float) -> float:
    return 111.2 * math.hypot(_num(site["dec_lat_va"]) - lat,
                              (_num(site["dec_long_va"]) - lon) * math.cos(math.radians(lat)))


def _area(site: dict) -> float:
    a = _num(site.get("drain_area_va"))
    return a if math.isfinite(a) else -1.0


class USGSNwis(Connector):
    name = "usgs_nwis"

    async def _sites(self, params: dict) -> list[dict]:
        # the site service answers 404 when nothing matches
        r = await self.http.request("GET", f"{NWIS}/site/", params=params, expected=(200, 404))
        return parse_rdb(r.text) if r.status_code == 200 else []

    async def find_sites(self, region: Region, params: list[str], start, end, site_type: str | None = None):
        q = {"format": "rdb", "parameterCd": ",".join(params), "siteStatus": "all", "hasDataTypeCd": "dv",
             "siteOutput": "expanded", "startDt": start.isoformat(), "endDt": end.isoformat()}
        if site_type:
            q["siteType"] = site_type
        # shortcut: polygons are searched by their bounding box; filter by polygon if users draw odd shapes
        if not region.is_point:
            w, s, e, n = region.bbox
            sites = await self._sites(q | {"bBox": f"{w:.6f},{s:.6f},{e:.6f},{n:.6f}"})
            return sorted(sites, key=lambda x: (-_area(x), x["site_no"]))
        lon, lat = region.point
        for pad in (0.25, 0.5):
            sites = await self._sites(q | {"bBox": f"{lon - pad:.6f},{lat - pad:.6f},{lon + pad:.6f},{lat + pad:.6f}"})
            if sites:
                return sorted(sites, key=lambda x: (_dist_km(x, lon, lat), x["site_no"]))
        return []

    async def _ogc(self, site: str, params: list[str], start, end):
        url, q, feats = OGC_DAILY, {
            "monitoring_location_id": f"USGS-{site}", "parameter_code": ",".join(params),
            "datetime": f"{start.isoformat()}/{end.isoformat()}", "f": "json", "limit": 50000,
            "skipGeometry": "true",
            "properties": "time,value,qualifier,approval_status,unit_of_measure,statistic_id,parameter_code"}, []
        first = None
        while url:
            r = await self.http.request("GET", url, params=q)
            first = first or r
            d = r.json()
            feats += d.get("features", [])
            url = next((ln["href"] for ln in d.get("links", []) if ln.get("rel") == "next"), None)
            q = None                         # the next link already carries the query
        return parse_ogc_daily(feats), first

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        params = list(v["usgs_parameter_cd"])
        site_id = str(req.options.get("site_id") or "").removeprefix("USGS-").strip()
        if site_id:
            try:
                site = (await self._sites({"format": "rdb", "sites": site_id, "siteOutput": "expanded",
                                           "siteStatus": "all"}) or [{}])[0]
            except UpstreamError:
                site = {}
            site = {"site_no": site_id, **site}
        else:
            await progress(0.05, "Finding USGS gauges (NWIS site service)")
            found = await self.find_sites(req.region, params, req.start, req.end, v.get("usgs_site_type"))
            if not found:
                where = "within about 0.5 deg of this point" if req.region.is_point else "inside this box"
                raise UpstreamUnavailable(
                    f"No USGS gauge with daily {v['name'].lower()} data {where} for the chosen period "
                    "(USGS gauges cover the United States). Move the point/box or give options.site_id.")
            site = found[0]
        sid = site["site_no"]
        await progress(0.3, f"Downloading daily values for USGS {sid}")
        notes = []
        try:
            r = await self.http.request("GET", f"{NWIS}/dv/", params={
                "format": "json", "sites": sid, "parameterCd": ",".join(params),
                "startDT": req.start.isoformat(), "endDT": req.end.isoformat()})
            best, api = pick_series(parse_nwis_dv(r.content), params), "usgs.nwis_dv"
        except UpstreamError as exc:
            notes.append(f"legacy NWIS dv failed ({exc.message}); used the USGS OGC API")
            cands, r = await self._ogc(sid, params, req.start, req.end)
            best, api = pick_series(cands, params), "usgs.ogcapi_daily"
        await progress(1.0, "USGS daily values downloaded")
        name = site.get("station_nm") or best.get("name")
        lat, lon = site.get("dec_lat_va") or best.get("lat"), site.get("dec_long_va") or best.get("lon")
        area = _num(site.get("drain_area_va"))
        notes = [f"site USGS-{sid} {name or '(name not reported)'} (lat {lat}, lon {lon})",
                 (f"drainage area {area:g} mi2 ({area * 2.589988:.0f} km2)" if math.isfinite(area)
                  else "drainage area not reported"),
                 "site given by user" if site_id else (
                     "nearest gauge to the point" if req.region.is_point
                     else "gauge with the largest drainage area in the box (most downstream)"),
                 f"parameter {best['param']} {best['variable']}, statistic {best['stat']}",
                 f"provisional values: {best['provisional']} of {len(best['v'])} (subject to revision by USGS)",
                 ] + notes
        prov = Provenance(
            source_api=api, variable=best["param"], geometry=req.region.as_dict(),
            dataset_short_name=(v.get("dataset") or {}).get("short_name", "USGS NWIS daily values"),
            version="WaterML 1.1 JSON (NWIS dv)" if api == "usgs.nwis_dv" else "OGC API v0 daily",
            product_id=f"USGS-{sid}", request_url=r.url, retrieved_at=r.retrieved_at, doi=NWIS_DOI,
            citation="U.S. Geological Survey, National Water Information System (USGS Water Data for the Nation)",
            notes=notes, from_cache=r.from_cache)
        # flagged and no-data values stay in the raw series; apply_qc masks them to NaN and counts them
        meta = ValueMeta(fill_values=(best["nodata"],) if best["nodata"] is not None else (), units=best["units"])
        return RawSeries(np.array(best["t"], "datetime64[ns]"), np.asarray(best["v"], float), "daily", prov, meta,
                         qc_pass=np.asarray(best["ok"], bool))
