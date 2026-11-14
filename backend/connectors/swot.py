"""SWOT water surface elevation from PO.DAAC Hydrocron (no auth; verified live 2026-11-14).

GET https://soto.podaac.earthdatacloud.nasa.gov/hydrocron/v1/timeseries
    ?feature=Reach|PriorLake&feature_id=..&start_time=..Z&end_time=..Z&output=csv&fields=..&collection_name=..
-> JSON {"status", "hits", "results": {"csv": "..."}}; HTTP 400 when the feature has no data in the window.

SWOT observes a reach or lake only a few times per 21-day repeat cycle (science orbit since July 2023),
so the record is short and sparse. Monthly values are the mean of the passes in that month.
"""
from __future__ import annotations

import csv
import io

import numpy as np

from ..core.errors import InvalidRequest, UpstreamError, UpstreamUnavailable
from ..timeseries.model import Provenance, RawSeries, ValueMeta
from .base import Connector, FetchRequest, ProgressFn, _noop

HYDROCRON = "https://soto.podaac.earthdatacloud.nasa.gov/hydrocron/v1/timeseries"
FILL = -999999999999.0
# id column and the source's summary quality flag (0 good/nominal, 1 suspect, 2 degraded, 3 bad)
FIELDS = {"Reach": ("reach_id", "reach_q"), "PriorLake": ("lake_id", "quality_f")}


def parse_hydrocron_csv(payload, feature: str) -> tuple[list[str], list[float], list[bool], dict]:
    id_col, q_col = FIELDS[feature]
    rows = list(csv.DictReader(io.StringIO(payload["results"]["csv"])))
    # unobserved passes come back as time_str "no_data": no time, so not a data point
    timed = [r for r in rows if r["time_str"] != "no_data"]
    # Hydrocron can repeat a pass verbatim; a repeated pass must not count twice in the monthly mean
    uniq = list({(r["time_str"], r["wse"]): r for r in timed}.values())
    t = [r["time_str"].rstrip("Z") for r in uniq]
    v = [float(r["wse"]) for r in uniq]
    ok = [r[q_col] != "3" for r in uniq]
    info = {"n_rows": len(rows), "n_no_data": len(rows) - len(timed), "n_duplicates": len(timed) - len(uniq),
            "collections": sorted({r["collection_shortname"] for r in rows}),
            "crids": sorted({r["crid"] for r in rows}), "units": rows[0].get("wse_units") if rows else None,
            "ids": sorted({r[id_col] for r in rows})}
    return t, v, ok, info


class SwotHydrocron(Connector):
    name = "swot_hydrocron"

    async def fetch(self, req: FetchRequest, progress: ProgressFn = _noop) -> RawSeries:
        v = req.variable
        feature = v["swot_feature"]
        fid = str(req.options.get("feature_id") or "").strip()
        if not fid:
            kind = "an 11-digit SWORD river reach id" if feature == "Reach" else "a 10-digit PLD prior-lake id"
            raise InvalidRequest(f"{v['name']} needs options.feature_id: {kind} "
                                 "(see https://podaac.github.io/hydrocron/).")
        ds = v.get("dataset") or {}
        id_col, q_col = FIELDS[feature]
        await progress(0.1, f"Requesting SWOT {feature} {fid} from Hydrocron")
        try:
            r = await self.http.request("GET", HYDROCRON, params={
                "feature": feature, "feature_id": fid, "output": "csv",
                "start_time": f"{req.start.isoformat()}T00:00:00Z", "end_time": f"{req.end.isoformat()}T23:59:59Z",
                "fields": f"{id_col},time_str,wse,{q_col},collection_shortname,crid",
                "collection_name": ds["short_name"]})
        except UpstreamError as exc:
            if (exc.detail or {}).get("status") == 400:
                raise UpstreamUnavailable(f"SWOT has no {feature} {fid} observations from {req.start} to "
                                          f"{req.end}: {(exc.detail or {}).get('body', '')[:200]}",
                                          detail=exc.detail) from exc
            raise
        t, val, ok, info = parse_hydrocron_csv(r.json(), feature)
        await progress(1.0, f"{len(t)} SWOT passes downloaded")
        n_months = len({x[:7] for x, good, y in zip(t, ok, val) if good and y != FILL})
        prov = Provenance(
            source_api="podaac.hydrocron", variable="wse", geometry=req.region.as_dict(),
            dataset_short_name=", ".join(info["collections"]) or ds.get("short_name"), version=ds.get("version"),
            concept_id=ds.get("concept_id"), product_id=f"{feature} {fid}", request_url=r.url,
            retrieved_at=r.retrieved_at, doi=ds.get("doi"),
            citation="SWOT Level 2 single-pass vector data via PO.DAAC Hydrocron",
            notes=[f"SWOT {feature} {fid}", f"crid (processing): {', '.join(info['crids'])}",
                   f"{len(t)} passes with a time over {n_months} month(s) with valid data; "
                   f"{info['n_no_data']} unobserved pass(es) and {info['n_duplicates']} repeated row(s) dropped",
                   "monthly value = mean of the SWOT passes in that month (a few passes per 21-day cycle), "
                   "not the daily-completeness rule",
                   "SWOT science orbit began July 2023: the record is too short for a reliable trend test"],
            from_cache=r.from_cache)
        # SWOT passes are sparse, so they are averaged per month directly ("monthly" path of to_monthly)
        return RawSeries(np.array(t, "datetime64[ns]"), np.asarray(val, float), "monthly", prov,
                         ValueMeta(fill_values=(FILL,), units=info["units"] or "m"), qc_pass=np.asarray(ok, bool))
