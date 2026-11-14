"""Giovanni area-averaged time series through Harmony (new Apr 2026, per reference doc).

harmony-py: Request(collection=Collection(id=<concept>), spatial=BBox(w,s,e,n), temporal=...,
            variables=[<id>], average="area", format="text/csv")
Output CSV: header block ending in a line that is only ",", then time,mean_<var>.

harmony-py is synchronous, so the call runs in a worker thread. The parsed CSV text is stored
in the raw cache under a request key, so the same request is never sent twice.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

from ..core.auth import edl_basic_auth
from ..core.errors import CredentialsMissing, InvalidRequest, UpstreamError, UpstreamUnavailable
from ..core.http import CachedResponse, request_key
from ..timeseries.model import Provenance, RawSeries, ValueMeta, utc_now_iso
from ..timeseries.parsers import parse_harmony_area_csv
from .base import Connector, FetchRequest, ProgressFn, _noop


class HarmonyArea(Connector):
    name = "giovanni.harmony_area"
    supports_point = False

    def _client(self):
        from harmony import Client
        if self.s.earthdata_token is not None:
            return Client(token=self.s.earthdata_token.get_secret_value())
        try:
            return Client(auth=edl_basic_auth(self.s))
        except CredentialsMissing:
            raise CredentialsMissing("Harmony needs EARTHDATA_TOKEN or Earthdata username/password") from None

    def _run_sync(self, concept_id: str, variable: str, region, start, end) -> list[str]:
        from harmony import BBox, Collection, Request
        client = self._client()
        kwargs = dict(collection=Collection(id=concept_id),
                      temporal={"start": datetime.combine(start, datetime.min.time()),
                                "stop": datetime.combine(end, datetime.max.time().replace(microsecond=0))},
                      variables=[variable], average="area", format="text/csv")
        tmp = Path(tempfile.mkdtemp(prefix="etd_harmony_"))
        if region.kind == "polygon":
            shp = tmp / "region.geojson"
            shp.write_text(json.dumps({"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": region.to_geojson()}]}))
            kwargs["shape"] = (open(shp, "rb"), "application/geo+json")  # noqa: SIM115 - harmony reads it
        else:
            w, s, e, n = region.bbox
            kwargs["spatial"] = BBox(w, s, e, n)
        req = Request(**kwargs)
        if not req.is_valid():
            raise InvalidRequest(f"Invalid Harmony request: {req.error_messages()}")
        job_id = client.submit(req)
        client.wait_for_processing(job_id, show_progress=False)
        files = [f.result() for f in client.download_all(job_id, directory=str(tmp), overwrite=True)]
        texts = []
        for f in files:
            if str(f).lower().endswith(".csv"):
                texts.append(Path(f).read_text(encoding="utf-8"))
        if not texts:
            raise UpstreamError("Harmony job finished without CSV output", detail={"job_id": job_id, "files": files})
        return texts

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        ds = v.get("dataset") or {}
        cid = ds.get("concept_id")
        if not cid:
            raise UpstreamUnavailable(f"No CMR concept id for {v['id']}; cannot run Harmony area average")
        if req.region.is_point:
            raise InvalidRequest("Harmony area average needs a bbox or polygon")
        # NASA tutorial (How_To_Access_the_Giovanni_Averaging_Service_Using_Python.ipynb) passes the
        # Giovanni variable ID, e.g. variables=["M2T1NXAER_5_12_4_DUCMASS"]; native name is a last resort.
        if req.options.get("check_quota", True):
            from .giovanni import GiovanniPoint
            await GiovanniPoint(self.s, self.http).check_quota()
        candidates = [v.get("harmony_variable") or v.get("giovanni_id"), ds.get("variable")]
        candidates = [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]
        last_exc: Exception | None = None
        for var in candidates:
            key = request_key("HARMONY", cid, {"var": var, "region": req.region.as_dict(),
                                                "start": str(req.start), "end": str(req.end)}, None, None)
            hit = self.http.cache.get(key)
            from_cache = hit is not None
            if hit:
                texts = json.loads(hit.content)
            else:
                await progress(0.05, "Submitting Harmony area-average job")
                try:
                    texts = await asyncio.to_thread(self._run_sync, cid, var, req.region, req.start, req.end)
                except (InvalidRequest, CredentialsMissing):
                    raise
                except Exception as exc:  # noqa: BLE001 - harmony raises plain Exceptions
                    last_exc = exc
                    continue
                self.http.cache.put(key, CachedResponse(200, json.dumps(texts).encode(), {}, f"harmony:{cid}",
                                                        utc_now_iso(), False))
            ts, vals, hdr = [], [], {}
            for tx in texts:
                h, t, val = parse_harmony_area_csv(tx)
                hdr.update(h)
                ts.append(t)
                vals.append(val)
            t = np.concatenate(ts)
            val = np.concatenate(vals)
            _, keep = np.unique(t, return_index=True)
            await progress(1.0, "Harmony job complete")
            prov = Provenance(
                source_api=self.name, variable=var, geometry=req.region.as_dict(),
                dataset_short_name=ds.get("short_name"), version=ds.get("version"), concept_id=cid,
                request_url=f"harmony:collection={cid};average=area;variables={var}", doi=ds.get("doi"),
                notes=["area-weighted mean computed by the Giovanni averaging service"], from_cache=from_cache,
            )
            units = hdr.get("units") or hdr.get("unit") or v.get("units")
            return RawSeries(t[keep], val[keep], v.get("native_resolution", "daily"), prov, ValueMeta(units=units))
        raise UpstreamUnavailable(f"Harmony area average failed for {v['id']}: {last_exc}",
                                  detail={"error": repr(last_exc)})
