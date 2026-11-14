"""Giovanni in the Cloud (GES DISC) — point time series.

GET {base}/timeseries?data=<id>&location=[lat,lon]&time=<start>/<end>   (Bearer EDL token)
Returns CSV: header block (param_name, unit, lat, lon, ...) then Timestamp,value rows.
Long requests are split into chunks so each one is cacheable and retryable on its own.
Source: nasa/gesdisc-tutorials How_to_Access_GiC_Time_Series_Service.ipynb (per reference doc).
"""
from __future__ import annotations

import asyncio
from datetime import date

import numpy as np

from ..core.auth import edl_bearer_headers
from ..core.errors import InvalidRequest, UpstreamError, UpstreamUnavailable
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from ..timeseries.parsers import _to_float, parse_giovanni_timeseries_csv
from .base import Connector, FetchRequest, ProgressFn, _noop

CHUNK_YEARS = {"hourly": 2, "3-hourly": 4, "daily": 8, "monthly": 50}


def year_chunks(start: date, end: date, years: int) -> list[tuple[date, date]]:
    out = []
    y = start.year
    while True:
        a = date(y, 1, 1) if y != start.year else start
        b_year = y + years - 1
        b = min(date(b_year, 12, 31), end)
        out.append((a, b))
        if b >= end:
            break
        y = b_year + 1
    return out


class GiovanniPoint(Connector):
    name = "giovanni.timeseries"
    supports_area = False

    async def configured_variables(self) -> list[str]:
        from ..timeseries.parsers import parse_configured_variables
        r = await self.http.request("GET", f"{self.s.giovanni_base}/configured-variables/")
        return parse_configured_variables(r.content)

    _quota_cache: dict = {"t": 0.0, "value": None}

    async def quota(self, max_age_s: float = 600.0) -> dict:
        """GET /quota -> {"status": 200, "quota": <fraction of monthly compute used>} (NASA tutorial format)."""
        import time as _t
        qc = GiovanniPoint._quota_cache
        if qc["value"] is not None and _t.monotonic() - qc["t"] < max_age_s:
            return qc["value"]
        r = await self.http.request("GET", f"{self.s.giovanni_base}/quota", headers=edl_bearer_headers(self.s),
                                    use_cache=False)
        try:
            d = r.json()
        except ValueError:
            d = {"raw": r.text[:200]}
        frac = d.get("quota") if isinstance(d, dict) else None
        out = {"fraction_used": float(frac) if isinstance(frac, (int, float)) else None, "raw": d}
        qc.update(t=_t.monotonic(), value=out)
        return out

    async def check_quota(self) -> None:
        """NASA's tutorial warns at >= 95 % of the monthly quota; we stop and fall back instead."""
        try:
            q = await self.quota()
        except Exception:  # noqa: BLE001 - quota endpoint trouble must not block data access
            return
        f = q.get("fraction_used")
        if f is not None and f >= self.s.giovanni_quota_stop:
            raise UpstreamUnavailable(f"Giovanni monthly quota is {f:.0%} used; using the fallback source",
                                      detail={"quota": q})

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        # monthly Giovanni ID (live-verified) when available: ~730x fewer rows than hourly for point requests
        gid = v.get("giovanni_point_id") or v.get("giovanni_id")
        if not gid:
            raise InvalidRequest(f"{v['id']} has no Giovanni variable id")
        if not req.region.is_point:
            raise InvalidRequest("Giovanni /timeseries is point-only; use the Harmony area connector")
        lon, lat = req.region.point
        headers = edl_bearer_headers(self.s)
        await self.check_quota()
        res = v.get("giovanni_point_resolution") if v.get("giovanni_point_id") else v.get("native_resolution", "daily")
        chunks = year_chunks(req.start, req.end, CHUNK_YEARS.get(res, 8))
        sem = asyncio.Semaphore(3)
        done = 0
        header_seen: dict = {}
        urls = []
        from_cache = True

        async def one(a: date, b: date):
            nonlocal done, from_cache
            # same parameter format as NASA's tutorial: location "[lat,lon]", time "start/end" (UTC)
            params = {"data": gid, "location": f"[{lat:.4f},{lon:.4f}]",
                      "time": f"{a.isoformat()}T00:00:00/{b.isoformat()}T23:59:59"}
            async with sem:
                try:
                    r = await self.http.request("GET", f"{self.s.giovanni_base}/timeseries", params=params,
                                                headers=headers)
                except UpstreamError as exc:
                    body = (exc.detail or {}).get("body", "").lower()
                    status = (exc.detail or {}).get("status")
                    if status in (400, 404) and ("variable" in body or "not" in body or "config" in body):
                        raise UpstreamUnavailable(f"Giovanni does not serve {gid}", detail=exc.detail) from exc
                    raise
            from_cache = from_cache and r.from_cache
            hdr, t, val = parse_giovanni_timeseries_csv(r.text)
            header_seen.update(hdr)
            urls.append(r.url)
            done += 1
            await progress(done / len(chunks), f"Giovanni chunk {done}/{len(chunks)}")
            return t, val

        parts = await asyncio.gather(*(one(a, b) for a, b in chunks))
        t = np.concatenate([p[0] for p in parts]) if parts else np.array([], "datetime64[ns]")
        val = np.concatenate([p[1] for p in parts]) if parts else np.array([])
        # de-duplicate chunk boundaries
        _, keep = np.unique(t, return_index=True)
        t, val = t[keep], val[keep]
        if len(t) == 0 or not np.isfinite(val).any():
            raise UpstreamUnavailable(f"Giovanni returned no valid data for {gid} at ({lat}, {lon})",
                                      detail={"hint": "Land-model variables are masked over ocean."})
        units = header_seen.get("unit") or header_seen.get("units") or v.get("units")
        long_name = header_seen.get("param_name")
        fill = _to_float(header_seen.get("fill_value")) if "fill_value" in header_seen else None
        ds = v.get("dataset") or {}
        prov = Provenance(
            source_api=self.name, variable=gid, geometry=req.region.as_dict(),
            dataset_short_name=ds.get("short_name"), version=ds.get("version"), concept_id=ds.get("concept_id"),
            request_url=urls[0].split("&time=")[0] if urls else None, doi=ds.get("doi"),
            notes=[f"{len(chunks)} request chunk(s)", f"grid cell centre lat={header_seen.get('lat')}, "
                                                       f"lon={header_seen.get('lon')}",
                   f"Giovanni parameter: {long_name}"],
            from_cache=from_cache,
        )
        return RawSeries(t, val, res, prov, ValueMeta(fill_values=(fill,) if fill is not None else (), units=units,
                                                     long_name=long_name))
