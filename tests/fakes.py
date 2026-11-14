"""Fake upstream services for offline tests.

IMPORTANT: response layouts are reconstructed from the descriptions in
docs/02-platforms-and-apis.md (no live access from the build sandbox). Run
scripts/live_smoke_test.py on a machine with credentials; it saves REAL responses to
tests/fixtures/recorded/, which should then replace these synthetic formats.

All data are synthetic with a known planted trend so tests can check that the full
pipeline recovers it.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import numpy as np
import pandas as pd
import xarray as xr

TREND_PER_YEAR = {"T2M": 0.03, "precipitation": -0.002, "NDVI": 0.004, "TAVG": 0.025, "default": 0.02}


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def synth(times: pd.DatetimeIndex, var: str, lat: float, lon: float, base: float, amp: float,
          noise: float, trend: float | None = None) -> np.ndarray:
    rng = np.random.default_rng(_seed(var, round(lat, 2), round(lon, 2)))
    yrs = (times - pd.Timestamp("2000-01-01")).days.to_numpy() / 365.25
    doy = times.dayofyear.to_numpy()
    tr = TREND_PER_YEAR.get(var, TREND_PER_YEAR["default"]) if trend is None else trend
    e = rng.normal(0, noise, len(times))
    # AR(1) persistence at monthly scale
    for i in range(1, len(e)):
        e[i] += 0.3 * e[i - 1]
    return base + amp * np.sin(2 * np.pi * (doy - 110) / 365.25) + tr * yrs + e


class FakeUpstream:
    def __init__(self):
        self.calls: list[str] = []
        self.task_polls: dict[str, int] = {}
        self.fail_once_429: set[str] = set()
        self.llm_reply: str | dict | None = None
        self.giovanni_missing: set[str] = set()
        self.quota = 0.03

    # ------------------------------------------------------------ dispatcher
    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        host, path = url.host, url.path
        self.calls.append(f"{request.method} {host}{path}")
        key = f"{host}{path}"
        if key in self.fail_once_429:
            self.fail_once_429.discard(key)
            return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")
        q = {k: v[0] for k, v in parse_qs(url.query.decode()).items()}
        if host == "api.giovanni.earthdata.nasa.gov":
            return self.giovanni(request, path, q)
        if host == "appeears.earthdatacloud.nasa.gov":
            return self.appeears(request, path, q)
        if host == "www.ncei.noaa.gov":
            return self.ncei(request, path, q)
        if host == "cmr.earthdata.nasa.gov":
            return self.cmr(request, path, q)
        if host == "opendap.earthdata.nasa.gov":
            return self.opendap(request, path, q)
        if host in ("127.0.0.1", "localhost"):
            return self.ollama(request, path)
        return httpx.Response(404, text=f"fake: no route for {host}{path}")

    # ------------------------------------------------------------ Giovanni
    def giovanni(self, request, path, q):
        if path.rstrip("/") == "/configured-variables":
            return httpx.Response(200, json=["M2T1NXSLV_5_12_4_T2M", "GPM_3IMERGM_07_precipitation",
                                             "GPM_3IMERGDF_07_precipitation", "AIRS3STD_006_SurfAirTemp_A"])
        if path == "/quota":
            return httpx.Response(200, json={"status": 200, "quota": self.quota})
        if path == "/timeseries":
            if not request.headers.get("authorization", "").startswith("Bearer "):
                return httpx.Response(401, text="unauthorized")
            gid = q["data"]
            if gid in self.giovanni_missing:
                return httpx.Response(400, text=f"variable {gid} is not configured")
            lat, lon = (float(x) for x in q["location"].strip("[]").split(","))
            a, b = q["time"].split("/")
            if gid.startswith("M2T1NXSLV"):
                times = pd.date_range(a[:10], b[:10] + " 23:00", freq="h")
                var, unit, vals = "T2M", "K", synth(times, "T2M", lat, lon, 300.0, 3.0, 0.6)
            elif gid.startswith("M2IMNXASM") or gid.startswith("GLDAS_NOAH025_M"):
                times = pd.date_range(a[:10], b[:10], freq="MS")
                var, unit, vals = "T2M", "K", synth(times, "T2M", lat, lon, 300.0, 3.0, 0.3)
            elif gid.startswith("GPM_3IMERGM"):
                times = pd.date_range(a[:10], b[:10], freq="MS")
                var, unit = "precipitation", "mm/hr"
                vals = np.clip(synth(times, "precipitation", lat, lon, 0.15, 0.12, 0.03), 0, None)
            else:
                times = pd.date_range(a[:10], b[:10], freq="D")
                var, unit = "precipitation", "mm/day"
                vals = np.clip(synth(times, "precipitation", lat, lon, 3.0, 2.5, 1.5), 0, None)
            vals = vals.copy()
            vals[::97] = -9999.0                               # fill values to be masked
            long = {"T2M": "Temperature at 2 m above the displacement height",
                    "precipitation": "Merged satellite-gauge precipitation estimate"}[var]
            # 13 key,value header lines, as in NASA's tutorial ("the first 13 rows are header")
            head = [f"prod_name,{gid.rsplit('_', 1)[0]}", f"param_short_name,{var}", f"param_name,{long}",
                    f"unit,{unit}", f"begin_time,{a}", f"end_time,{b}", f"lat,{round(lat * 2) / 2}",
                    f"lon,{round(lon / 0.625) * 0.625}", f"request_lat,{lat}", f"request_lon,{lon}",
                    "fill_value,-9999", "shape,point", "dataset,GiC"]
            body = "\n".join(head + [",", f"Timestamp (UTC),{long}"] +
                             [f"{t.strftime('%Y-%m-%dT%H:%M:%S')},{v:.4f}" for t, v in zip(times, vals)])
            return httpx.Response(200, text=body, headers={"content-type": "text/csv"})
        return httpx.Response(404)

    # ------------------------------------------------------------ AppEEARS
    def appeears(self, request, path, q):
        p = path.replace("/api", "", 1)
        if p == "/login" and request.method == "POST":
            if "authorization" not in request.headers:
                return httpx.Response(401)
            return httpx.Response(200, json={"token_type": "Bearer", "token": "fake-appeears-token",
                                             "expiration": "2099-01-01T00:00:00Z"})
        auth_ok = request.headers.get("authorization") == "Bearer fake-appeears-token"
        if p.startswith("/product/"):
            return httpx.Response(200, json={
                "_1_km_monthly_NDVI": {"FillValue": -3000, "ScaleFactor": 0.0001, "ValidMin": -2000,
                                       "ValidMax": 10000, "Units": "NDVI", "Description": "1 km monthly NDVI"},
                "_1_km_monthly_pixel_reliability": {"FillValue": -1, "ValidMin": -1, "ValidMax": 3,
                                                    "Units": "rank"}})
        if not auth_ok:
            return httpx.Response(403, text="token required")
        if p == "/task" and request.method == "POST":
            body = json.loads(request.content)
            tid = "task" + hashlib.sha256(request.content).hexdigest()[:8]
            self.task_polls[tid] = 0
            self._task_bodies = getattr(self, "_task_bodies", {})
            self._task_bodies[tid] = body
            return httpx.Response(202, json={"task_id": tid, "status": "pending"})
        m = re.fullmatch(r"/task/(\w+)", p)
        if m:
            tid = m.group(1)
            self.task_polls[tid] = self.task_polls.get(tid, 0) + 1
            st = "done" if self.task_polls[tid] >= 2 else "processing"
            return httpx.Response(200, json={"task_id": tid, "status": st})
        m = re.fullmatch(r"/bundle/(\w+)", p)
        if m:
            return httpx.Response(200, json={"task_id": m.group(1), "files": [
                {"file_id": "f1", "file_name": "etd-MOD13A3-061-results.csv", "file_type": "csv"},
                {"file_id": "f2", "file_name": "etd-request.json", "file_type": "json"}]})
        m = re.fullmatch(r"/bundle/(\w+)/f1", p)
        if m:
            body = self._task_bodies[m.group(1)]
            c = body["params"]["coordinates"][0]
            d = body["params"]["dates"][0]
            times = pd.date_range(pd.to_datetime(d["startDate"], format="%m-%d-%Y"),
                                  pd.to_datetime(d["endDate"], format="%m-%d-%Y"), freq="MS")
            ndvi = np.clip(synth(times, "NDVI", c["latitude"], c["longitude"], 0.45, 0.15, 0.03), -0.2, 1)
            rel = np.zeros(len(times), int)
            rel[5::23] = 3                                   # cloudy -> must be masked by QC
            ndvi[11::41] = -0.3                              # scaled fill
            rows = ["ID,Latitude,Longitude,Date,MODIS_Tile,MOD13A3_061__1_km_monthly_NDVI,"
                    "MOD13A3_061__1_km_monthly_pixel_reliability"]
            rows += [f"p1,{c['latitude']},{c['longitude']},{t.date()},h25v06,{v:.4f},{r}"
                     for t, v, r in zip(times, ndvi, rel)]
            return httpx.Response(200, text="\n".join(rows))
        return httpx.Response(404)

    # ------------------------------------------------------------ NOAA
    def ncei(self, request, path, q):
        if path.startswith("/access/services/data/v1"):
            stations = q["stations"].split(",")
            times = pd.date_range(q["startDate"], q["endDate"], freq="MS")
            out = []
            for k, sid in enumerate(stations):
                vals = synth(times, q["dataTypes"], 13 + k, 80 + k, 28.0 + k, 3.0, 0.5)
                for t, v in zip(times, vals):
                    out.append({"DATE": t.strftime("%Y-%m"), "STATION": sid,
                                q["dataTypes"]: f"{v:7.2f}" if (t.month + k) % 17 else ""})
            return httpx.Response(200, json=out)
        if path.endswith("/stations"):
            if "token" not in request.headers:
                return httpx.Response(400, text="token required")
            return httpx.Response(200, json={"metadata": {"resultset": {"count": 2}}, "results": [
                {"id": "GHCND:IN012070800", "name": "CHENNAI MINAMBAKKAM, IN", "latitude": 13.0, "longitude": 80.18,
                 "mindate": "1950-01-01", "maxdate": "2025-10-01", "datacoverage": 0.95},
                {"id": "GHCND:IN012070900", "name": "CHENNAI NUNGAMBAKKAM, IN", "latitude": 13.07, "longitude": 80.25,
                 "mindate": "1990-01-01", "maxdate": "2025-10-01", "datacoverage": 0.9}]})
        return httpx.Response(404)

    # ------------------------------------------------------------ CMR / OPeNDAP
    def cmr(self, request, path, q):
        if path.endswith("/granules.json"):
            cid = q["concept_id"]
            a, b = q["temporal"].split(",")
            months = pd.date_range(a[:10], b[:10], freq="MS")
            short = {"C1276812859-GES_DISC": "M2TMNXSLV.5.12.4", "C2723754851-GES_DISC": "GPM_3IMERGM.07",
                     "C1342986036-GES_DISC": "GLDAS_NOAH025_M.2.1"}.get(cid, "X.1")
            entries = [{"id": f"G{i}", "title": f"{short}:FILE.{t.strftime('%Y%m')}.nc4",
                        "time_start": t.strftime("%Y-%m-%dT00:00:00.000Z")} for i, t in enumerate(months)]
            return httpx.Response(200, json={"feed": {"entry": entries}})
        if path.endswith("/collections.json"):
            return httpx.Response(200, json={"feed": {"entry": [{"id": q.get("concept_id", "C1"), "time_start":
                                                                 "1980-01-01T00:00:00.000Z", "title": "fake"}]}})
        return httpx.Response(404)

    GRID_LAT = np.arange(-90, 90.01, 0.5)
    GRID_LON = np.arange(-180, 179.99, 0.625)

    def opendap(self, request, path, q):
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return httpx.Response(401)
        m = re.match(r"/collections/([^/]+)/granules/(.+?)\.(dmr\.xml|dap\.nc4)$", path)
        if not m:
            return httpx.Response(404)
        title = unquote(m.group(2))
        if m.group(3) == "dmr.xml":
            xml = ('<?xml version="1.0"?><Dataset xmlns="http://xml.opendap.org/ns/DAP/4.0#" name="g">'
                   '<Dimension name="time" size="1"/><Dimension name="lat" size="361"/><Dimension name="lon" size="576"/>'
                   '<Float32 name="T2M"><Dim name="/time"/><Dim name="/lat"/><Dim name="/lon"/></Float32>'
                   '<Float32 name="precipitation"><Dim name="/time"/><Dim name="/lon"/><Dim name="/lat"/></Float32>'
                   '</Dataset>')
            return httpx.Response(200, text=xml)
        ce = q.get("dap4.ce", "")
        if ce in ("/lat;/lon", "/lon;/lat"):
            ds = xr.Dataset(coords={"lat": self.GRID_LAT, "lon": self.GRID_LON})
        else:
            mm = re.match(r"/(\w+)\[0:1:0\]\[(\d+):1:(\d+)\]\[(\d+):1:(\d+)\]", ce)
            var = mm.group(1)
            a, b, c, d = (int(x) for x in mm.groups()[1:])
            month = pd.Timestamp(title.split(".")[-2] + "01")
            if var == "T2M":
                lat, lon = self.GRID_LAT[a:b + 1], self.GRID_LON[c:d + 1]
                LA, LO = np.meshgrid(lat, lon, indexing="ij")
                # gradient of trend across the box: half warming, half cooling -> mixed trend map
                tr = np.where(LO < LO.mean(), 0.06, -0.06)
                yrs = (month - pd.Timestamp("2000-01-01")).days / 365.25
                rng = np.random.default_rng(_seed(var, title))
                data = (290 + 8 * math.sin(2 * math.pi * (month.month - 4) / 12) + tr * yrs
                        + rng.normal(0, 0.4, LA.shape))[None]
                ds = xr.Dataset({"T2M": (("time", "lat", "lon"), data.astype("float32"), {"units": "K"})},
                                coords={"lat": lat, "lon": lon, "time": [month]})
            else:
                lon, lat = self.GRID_LON[a:b + 1], self.GRID_LAT[c:d + 1]
                rng = np.random.default_rng(_seed(var, title))
                data = np.abs(0.2 + 0.1 * math.sin(2 * math.pi * month.month / 12)
                              + rng.normal(0, 0.02, (len(lon), len(lat))))[None]
                ds = xr.Dataset({var: (("time", "lon", "lat"), data.astype("float32"), {"units": "mm/hr"})},
                                coords={"lon": lon, "lat": lat, "time": [month]})
        buf = io.BytesIO()
        ds.to_netcdf(buf, engine="h5netcdf")
        return httpx.Response(200, content=buf.getvalue(), headers={"content-type": "application/x-netcdf"})

    # ------------------------------------------------------------ Ollama
    def ollama(self, request, path):
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
        if path == "/api/chat":
            body = json.loads(request.content)
            reply = self.llm_reply
            if callable(reply):
                reply = reply(body)
            if isinstance(reply, dict):
                reply = json.dumps(reply)
            return httpx.Response(200, json={"message": {"role": "assistant", "content": reply or ""}})
        return httpx.Response(404)


def transport(fake: FakeUpstream) -> httpx.MockTransport:
    return httpx.MockTransport(fake.handler)


HARMONY_FREQ = {"C2723754851-GES_DISC": ("MS", "mm/hr", 0.15, 0.12, 0.03, "precipitation"),
                "C1276812863-GES_DISC": ("h", "K", 300.0, 3.0, 0.6, "T2M"),
                "C2723754864-GES_DISC": ("D", "mm/day", 3.0, 2.5, 1.5, "precipitation")}


def fake_harmony_run_sync(self, concept_id, variable, region, start, end) -> list[str]:
    """Stands in for harmony-py (which uses `requests`, not httpx). Output layout per reference doc:
    header block, a line that is only ',', then time,mean_<var>."""
    freq, unit, base, amp, noise, var = HARMONY_FREQ.get(concept_id, ("MS", "1", 1.0, 0.1, 0.05, "x"))
    times = pd.date_range(str(start), str(end) + (" 23:00" if freq == "h" else ""), freq=freq)
    lon, lat = region.centroid
    vals = synth(times, var, lat, lon, base, amp, noise)
    if unit.startswith("mm"):
        vals = np.clip(vals, 0, None)
    head = [f"collection,{concept_id}", f"variable,{variable}", f"units,{unit}",
            f"bbox,{','.join(str(x) for x in region.bbox)}", ","]
    return ["\n".join(head + [f"time,mean_{var}"] + [f"{t.isoformat()},{v:.5f}" for t, v in zip(times, vals)])]
