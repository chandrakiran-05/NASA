"""AppEEARS API (LP DAAC) — MODIS/VIIRS land products, SMAP, DAYMET.

Flow (reference doc §5): POST /login (Basic EDL) -> token (~48 h)
                         GET /product/{id}  -> layer metadata (FillValue, ScaleFactor, ValidMin/Max, Units)
                         POST /task (point | area) -> task_id
                         GET /task/{task_id} until status == done  (typically ~15 min)
                         GET /bundle/{task_id} -> files -> GET /bundle/{task_id}/{file_id} (302 to S3)
Dates are MM-DD-YYYY. GPM is NOT in AppEEARS.

Running task ids are persisted on disk, so a restarted server resumes polling the same task
instead of submitting a duplicate.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import time
from pathlib import Path

import numpy as np

from ..core.auth import edl_basic_auth
from ..core.errors import InvalidRequest, UpstreamError
from ..timeseries.gridded import area_mean, open_many
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from ..timeseries.parsers import appeears_column_name, parse_appeears_point_csv
from .base import Connector, FetchRequest, ProgressFn, _noop

DONE = {"done"}
FAILED = {"error", "failed", "expired", "deleted"}


def _ci(d: dict, *names, default=None):
    low = {k.lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low and low[n.lower()] not in (None, ""):
            return low[n.lower()]
    return default


def qc_pass_from_rule(qc_values: np.ndarray, rule: dict | None) -> np.ndarray | None:
    if rule is None or qc_values is None:
        return None
    q = np.asarray(qc_values, float)
    ok = np.isfinite(q)
    qi = np.where(ok, q, -1).astype(np.int64)
    if rule.get("rule") == "in":
        return ok & np.isin(qi, rule["values"])
    if rule.get("rule") == "bits":
        return ok & np.isin(qi & int(rule["mask"]), rule["values"])
    return None


class AppEEARS(Connector):
    name = "appeears"

    def __init__(self, settings, http):
        super().__init__(settings, http)
        self._token: str | None = None
        self._token_t = 0.0
        self._task_dir = settings.cache_dir / "appeears_tasks"
        self._task_dir.mkdir(parents=True, exist_ok=True)
        self.base = settings.appeears_base.rstrip("/")

    async def _auth_headers(self) -> dict:
        if self._token is None or time.time() - self._token_t > 40 * 3600:
            r = await self.http.request("POST", f"{self.base}/login", auth=edl_basic_auth(self.s), use_cache=False)
            self._token = r.json()["token"]
            self._token_t = time.time()
        return {"Authorization": f"Bearer {self._token}"}

    async def layer_meta(self, product_id: str) -> dict:
        r = await self.http.request("GET", f"{self.base}/product/{product_id}")
        return r.json()

    @staticmethod
    def value_meta(layers: dict, layer: str, units_default: str | None) -> ValueMeta:
        m = layers.get(layer, {})
        fill = _ci(m, "FillValue", "Fill_Value", "_FillValue")
        fills = tuple(float(x) for x in (fill if isinstance(fill, list) else [fill]) if x is not None)
        sf = _ci(m, "ScaleFactor", "scale_factor")
        off = _ci(m, "AddOffset", "add_offset", "Offset")
        vmin, vmax = _ci(m, "ValidMin"), _ci(m, "ValidMax")
        return ValueMeta(
            fill_values=fills,
            scale_factor=float(sf) if sf not in (None, "", 1, 1.0, "1") else None,
            add_offset=float(off) if off not in (None, "", 0, "0") else None,
            valid_min=float(vmin) if vmin is not None else None,
            valid_max=float(vmax) if vmax is not None else None,
            units=_ci(m, "Units", default=units_default),
            long_name=_ci(m, "Description"),
        )

    def _task_body(self, req: FetchRequest, name: str) -> dict:
        v = req.variable
        layers = [{"product": v["product_id"], "layer": v["layer"]}]
        if v.get("qc"):
            layers.append({"product": v["product_id"], "layer": v["qc"]["layer"]})
        dates = [{"startDate": req.start.strftime("%m-%d-%Y"), "endDate": req.end.strftime("%m-%d-%Y")}]
        if req.region.is_point:
            lon, lat = req.region.point
            return {"task_type": "point", "task_name": name,
                    "params": {"dates": dates, "layers": layers,
                               "coordinates": [{"id": "p1", "category": "etd", "latitude": lat, "longitude": lon}]}}
        return {"task_type": "area", "task_name": name,
                "params": {"dates": dates, "layers": layers,
                           "geo": {"type": "FeatureCollection", "features": [
                               {"type": "Feature", "properties": {}, "geometry": req.region.to_geojson()}]},
                           "output": {"format": {"type": "netcdf4"}, "projection": "geographic"}}}

    async def _submit_or_resume(self, body: dict) -> str:
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:20]
        p = self._task_dir / f"{key}.json"
        if p.exists():
            return json.loads(p.read_text())["task_id"]
        body = {**body, "task_name": f"etd-{key}"}
        r = await self.http.request("POST", f"{self.base}/task", json_body=body, headers=await self._auth_headers(),
                                    use_cache=False, expected=(200, 201, 202))
        task_id = r.json()["task_id"]
        p.write_text(json.dumps({"task_id": task_id, "submitted": time.time()}))
        return task_id

    async def _wait(self, task_id: str, progress: ProgressFn) -> None:
        t0 = time.time()
        while True:
            r = await self.http.request("GET", f"{self.base}/task/{task_id}", headers=await self._auth_headers(),
                                        use_cache=False)
            st = str(r.json().get("status", "")).lower()
            elapsed = (time.time() - t0) / 60
            if st in DONE:
                return
            if st in FAILED:
                raise UpstreamError(f"AppEEARS task {task_id} ended with status {st}", detail=r.json())
            if elapsed > self.s.appeears_timeout_min:
                raise UpstreamError(f"AppEEARS task {task_id} still '{st}' after {elapsed:.0f} min; "
                                    "the job keeps running upstream and will be resumed on the next request")
            await progress(min(0.1 + 0.8 * elapsed / 15.0, 0.9), f"AppEEARS task {st} ({elapsed:.1f} min)")
            await asyncio.sleep(self.s.appeears_poll_s)

    async def _download(self, task_id: str, want_ext: tuple[str, ...]) -> list[tuple[str, bytes]]:
        h = await self._auth_headers()
        r = await self.http.request("GET", f"{self.base}/bundle/{task_id}", headers=h, use_cache=False)
        files = r.json().get("files", [])
        out = []
        for f in files:
            name = f.get("file_name", "")
            if not name.lower().endswith(want_ext):
                continue
            fr = await self.http.request("GET", f"{self.base}/bundle/{task_id}/{f['file_id']}", headers=h)
            out.append((name, fr.content))
        if not out:
            raise UpstreamError(f"AppEEARS bundle {task_id} has no {want_ext} files",
                                detail={"files": [f.get("file_name") for f in files][:30]})
        return out

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        if not v.get("product_id") or not v.get("layer"):
            raise InvalidRequest(f"{v['id']} is not an AppEEARS variable")
        await progress(0.01, "Reading AppEEARS layer metadata")
        layers = await self.layer_meta(v["product_id"])
        meta = self.value_meta(layers, v["layer"], v.get("units"))
        body = self._task_body(req, "etd")
        task_id = await self._submit_or_resume(body)
        await progress(0.05, f"AppEEARS task {task_id} submitted")
        await self._wait(task_id, progress)
        ds_meta = v.get("dataset") or {}
        qc_rule = v.get("qc")
        if req.region.is_point:
            files = await self._download(task_id, (".csv",))
            name, content = next(((n, c) for n, c in files if v["product_id"].split(".")[0] in n), files[0])
            qc_col = appeears_column_name(v["product_id"], qc_rule["layer"]) if qc_rule else None
            t, val, qc = parse_appeears_point_csv(content.decode(), v["product_id"], v["layer"], "p1", qc_col)
            qc_pass = qc_pass_from_rule(qc, qc_rule)
            notes = [f"AppEEARS point task {task_id}", "scaling of CSV values auto-detected in QC step"]
        else:
            files = await self._download(task_id, (".nc", ".nc4"))
            tmp = Path(tempfile.mkdtemp(prefix="etd_appeears_"))
            paths = []
            for n, c in files:
                p = tmp / Path(n).name
                p.write_bytes(c)
                paths.append(p)
            ds = open_many(paths)
            qc_good = None
            if qc_rule and qc_rule["layer"] in ds:
                qv = ds[qc_rule["layer"]].values
                qc_good = qc_pass_from_rule(qv, qc_rule).reshape(qv.shape)
            t, val, frac = area_mean(ds, v["layer"], req.region, qc_good)
            qc_pass = None
            meta = ValueMeta(units=meta.units, valid_min=None, valid_max=None, already_scaled=True)
            notes = [f"AppEEARS area task {task_id}", "netCDF decoded with CF scale/fill; cos(lat)-weighted mean",
                     f"median valid-pixel fraction {float(np.nanmedian(frac)):.2f}"]
        await progress(1.0, "AppEEARS data downloaded")
        prov = Provenance(source_api=f"{self.name}.{'point' if req.region.is_point else 'area'}", variable=v["layer"],
                          geometry=req.region.as_dict(), dataset_short_name=ds_meta.get("short_name"),
                          version=ds_meta.get("version"), product_id=v["product_id"],
                          request_url=f"{self.base}/task/{task_id}", doi=ds_meta.get("doi"), notes=notes)
        return RawSeries(t, val, v.get("native_resolution", "monthly"), prov, meta, qc_pass=qc_pass)
