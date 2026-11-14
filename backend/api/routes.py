"""REST endpoints (architecture §2 plus insights / AI / investigation extensions)."""
from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import ORJSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from ..analysis.deseason import climatology_anomalies, deseasonalize
from ..analysis.engine import _clean
from ..catalog.catalog import DATA as CATALOG_DATA
from ..connectors.base import FetchRequest
from ..core.auth import credential_status
from ..core.errors import InvalidRequest, NotFound
from ..core.geometry import parse_geometry
from ..insights.compare import compare_regions
from ..insights.cube import cube_trends
from ..insights.drivers import driver_analysis
from ..insights.emergence import annual_means
from ..storage.series_store import frame_to_records
from ..timeseries.model import MonthlySeries, Provenance
from ..timeseries.service import parse_date
from . import pipeline
from ..novelty.agreement import product_agreement, second_opinions
from ..novelty.court import court as run_court
from ..novelty.evidence_clock import evidence_clock
from ..novelty.integrity import integrity_audit
from ..novelty.nulls import null_lineup
from ..novelty.scan import rank_and_cohere
from .schemas import (AnalyzeRequest, CompareRequest, DriversRequest, ExplainRequest, InsightsRequest,
                      InvestigateRequest, NullsRequest, ScanRequest, TextRequest, TimeseriesRequest,
                      TrendMapRequest, UploadSeries)
from .state import AppState

router = APIRouter(prefix="/api", default_response_class=ORJSONResponse)
DEMOS = json.loads((CATALOG_DATA / "demos.json").read_text())["demos"]


def S(request: Request) -> AppState:
    return request.app.state.etd


# ===================================================================== meta
@router.get("/health", tags=["meta"])
async def health(request: Request):
    st = S(request)
    return {"status": "ok", "version": request.app.version, "catalog_variables": len(st.catalog.ids),
            "catalog_built_at": st.catalog.built_at}


@router.get("/sources/status", tags=["meta"])
async def sources_status(request: Request, check_quota: bool = False):
    st = S(request)
    out = {"credentials": credential_status(st.settings), "alerts": st.catalog.alerts,
           "http": st.http.stats, "llm": await st.llm.status(), "catalog_built_at": st.catalog.built_at}
    if check_quota and st.settings.earthdata_token is not None:
        try:
            out["giovanni_quota"] = await st.ts.connectors["giovanni_point"].quota()
        except Exception as exc:  # noqa: BLE001
            out["giovanni_quota"] = {"error": str(exc)}
    return out


# ===================================================================== catalog
@router.get("/variables", tags=["catalog"])
async def list_variables(request: Request, q: str | None = None, domain: str | None = None,
                         region_type: str | None = None, source: str | None = None, limit: int = Query(20, le=200)):
    return {"variables": S(request).catalog.search(q, domain, region_type, source, limit)}


@router.get("/variables/{variable_id}", tags=["catalog"])
async def get_variable(request: Request, variable_id: str):
    return S(request).catalog.detail(variable_id)


@router.get("/regions/archetypes", tags=["catalog"])
async def archetypes(request: Request):
    return {"archetypes": S(request).catalog.archetypes}


@router.get("/regions/search", tags=["catalog"])
async def region_search(request: Request, q: str = Query(..., min_length=2), point: bool = False):
    from ..ai import gazetteer
    hits = gazetteer.find_places(q, max_n=5) or ([gazetteer.lookup(q)] if gazetteer.lookup(q) else [])
    out = []
    for h in hits:
        r = gazetteer.place_to_region(h, as_point=point)
        if r:
            out.append({"name": h["name"], "kind": h["type"], "approximate": bool(h.get("approximate")),
                        "geometry": r.as_dict()})
    return {"results": out}


# ===================================================================== time series
@router.post("/timeseries", status_code=202, tags=["timeseries"])
async def create_timeseries(request: Request, body: TimeseriesRequest):
    st = S(request)
    region = parse_geometry(body.geometry)
    start, end = parse_date(body.start), parse_date(body.end, end=True)
    st.ts.validate(body.variable_id, region, start, end)   # fail fast with 422 before queuing

    async def job(progress):
        return await st.ts.build_series(body.variable_id, region, start, end, options=body.options,
                                        progress=progress, refresh=body.refresh)

    jid = st.jobs.submit("timeseries", body.model_dump(), job)
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}"}


@router.get("/jobs/{job_id}", tags=["timeseries"])
async def get_job(request: Request, job_id: str, wait: float = Query(0, ge=0, le=30)):
    st = S(request)
    j = await st.jobs.wait(job_id, wait) if wait else st.db.get_job(job_id)
    if not j:
        raise NotFound(f"job {job_id} not found")
    return {"job_id": j["job_id"], "kind": j["kind"], "status": j["status"], "progress": j["progress"],
            "message": j["message"], "result": j.get("result"), "error": j.get("error"),
            "created_at": j["created_at"], "updated_at": j["updated_at"]}


@router.get("/series", tags=["timeseries"])
async def list_series(request: Request, limit: int = Query(50, le=500)):
    return {"series": S(request).db.list_series(limit)}


@router.get("/timeseries/{series_id}", tags=["timeseries"])
async def get_timeseries(request: Request, series_id: str,
                         view: str = Query("monthly", pattern="^(raw|monthly|deseasonalized|anomaly|annual)$")):
    st = S(request)
    ms = st.store.load(series_id)
    if view in ("raw", "monthly"):
        data = frame_to_records(ms.time, ms.value)
    elif view == "deseasonalized":
        d = await run_in_threadpool(deseasonalize, ms, "stl")
        data = frame_to_records(ms.time, d.deseasonalized)
    elif view == "anomaly":
        d = climatology_anomalies(ms)
        data = frame_to_records(ms.time, d.deseasonalized - np.nanmean(ms.value))
    else:
        a = annual_means(ms.time, ms.value)
        data = {"time": [f"{y}-07-01" for y in a.index], "value": [float(v) for v in a.to_numpy()]}
    return _clean({"series_id": series_id, "view": view, "label": ms.label, "units": ms.units, **data,
                   "n_valid": ms.n_valid, "completeness": ms.completeness(), "provenance": ms.provenance.to_dict(),
                   "note": "Stored series are monthly; 'raw' returns the monthly values." if view == "raw" else None})


@router.post("/timeseries/upload", tags=["timeseries"])
async def upload_series(request: Request, body: UploadSeries):
    """Bring your own series (e.g. a CSV exported from Giovanni or KNMI Climate Explorer)."""
    st = S(request)
    ms = MonthlySeries.from_arrays(body.time, [np.nan if v is None else v for v in body.value], units=body.units,
                                   provenance=Provenance(source_api="user_upload", variable=body.label or "value",
                                                         geometry={}), label=body.label)
    sid = st.ts.save_user_series(ms, body.label)
    return {"series_id": sid, "completeness": ms.completeness()}


@router.post("/timeseries/upload-csv", tags=["timeseries"])
async def upload_csv(request: Request, file: UploadFile = File(...), label: str | None = Form(None),
                     units: str | None = Form(None)):
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise InvalidRequest("CSV larger than 20 MB")
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.lower().split(",")[0].strip().startswith(("time", "date", "timestamp"))), 0)
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    tcol = df.columns[0]
    vcol = next((c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])), None)
    if vcol is None:
        raise InvalidRequest("No numeric value column found")
    body = UploadSeries(time=df[tcol].astype(str).tolist(), value=[None if pd.isna(v) else float(v) for v in df[vcol]],
                        units=units, label=label or f"{file.filename}:{vcol}")
    return await upload_series(request, body)


@router.get("/export/{series_id}", tags=["timeseries"])
async def export_series(request: Request, series_id: str, format: str = Query("csv", pattern="^(csv|json)$")):
    st = S(request)
    ms = st.store.load(series_id)
    prov = ms.provenance.to_dict()
    citation = prov.get("citation") or (
        f"{prov.get('dataset_short_name')} v{prov.get('version')}" + (f", doi:{prov['doi']}" if prov.get("doi") else "")
        + f". Retrieved via {prov.get('source_api')} on {prov.get('retrieved_at')}.")
    if format == "json":
        return _clean({"series_id": series_id, "label": ms.label, "units": ms.units,
                       **frame_to_records(ms.time, ms.value), "provenance": prov, "citation": citation})
    buf = io.StringIO()
    buf.write(f"# {ms.label}\n# units: {ms.units}\n# citation: {citation}\n# provenance: {json.dumps(prov, default=str)}\n")
    ms.to_frame().to_csv(buf, index=False, date_format="%Y-%m-%d")
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{series_id}.csv"'})


# ===================================================================== analysis
@router.post("/analyze", tags=["analysis"])
async def analyze(request: Request, body: AnalyzeRequest):
    st = S(request)
    res = await pipeline.cached_analysis(st, body.series_id, alpha=body.alpha, method=body.method_name(),
                                         mk_variant=body.mk_variant, include_series=body.include_series)
    if body.include_court:
        res = {**res, "court": await pipeline.cached_novelty(st, "court", body.series_id,
                                                              lambda ms: run_court(ms, body.alpha),
                                                              {"alpha": body.alpha})}
    return res


# ===================================================================== novelty (team spec F1-F5 + scan)
@router.get("/timeseries/{series_id}/integrity", tags=["novelty"])
async def integrity(request: Request, series_id: str):
    """F1 Seam & Integrity Audit: fit-for-trends badge, coverage strip, flags, seams, trend-or-jump."""
    def fn(ms):
        from ..analysis.deseason import deseasonalize
        return integrity_audit(ms, deseasonalize(ms, "stl").deseasonalized)
    return await pipeline.cached_novelty(S(request), "integrity", series_id, fn, {})


@router.get("/analyze/{series_id}/court", tags=["novelty"])
async def court_endpoint(request: Request, series_id: str, alpha: float = Query(0.05, gt=0, lt=0.5)):
    """F3 Method Verdict / Trend Court."""
    return await pipeline.cached_novelty(S(request), "court", series_id, lambda ms: run_court(ms, alpha),
                                         {"alpha": alpha})


@router.get("/analyze/{series_id}/detectability", tags=["novelty"])
async def detectability_endpoint(request: Request, series_id: str, start: int | None = None, end: int | None = None,
                                 min_years: int = Query(10, ge=3, le=50), alpha: float = Query(0.05, gt=0, lt=0.5)):
    """F2 Evidence Clock: triangle, expanding window, years-to-detect, cherry-pick rank of [start, end]."""
    return await pipeline.cached_novelty(
        S(request), "clock", series_id,
        lambda ms: evidence_clock(ms, start=start, end=end, min_years=min_years, alpha=alpha),
        {"start": start, "end": end, "min_years": min_years, "alpha": alpha})


@router.post("/analyze/nulls", tags=["novelty"])
async def nulls(request: Request, body: NullsRequest):
    """F5 Could It Be Chance? block-bootstrap null histogram + lineup."""
    return await pipeline.cached_novelty(
        S(request), "nulls", body.series_id,
        lambda ms: null_lineup(ms, n_null=body.n_null, n_panels=body.n_panels, block=body.block, seed=body.seed),
        body.model_dump(exclude={"series_id"}))


@router.get("/variables/{variable_id}/second-opinions", tags=["novelty"])
async def second_opinion_candidates(request: Request, variable_id: str):
    """F4: which other products/stations measure the same quantity."""
    S(request).catalog.get(variable_id)
    return second_opinions(variable_id)


@router.post("/scan", status_code=202, tags=["novelty"])
async def scan(request: Request, body: ScanRequest):
    """Trend Scan: many variables, one region; FDR across variables; physical-coherence check."""
    st = S(request)
    region = parse_geometry(body.geometry)
    start, end = parse_date(body.start), parse_date(body.end, end=True)
    if body.variable_ids:
        vids = body.variable_ids
    elif body.region_type and st.catalog.archetype(body.region_type):
        vids = [v["id"] for v in st.catalog.archetype(body.region_type)["variables"]]
    else:
        vids = ["merra2_t2m", "imerg_precip_monthly", "gldas_soilmoist_0_10", "modis_ndvi_monthly", "modis_lst_day"]
    for v in vids:
        st.catalog.get(v)

    async def job(progress):
        analyses, failures = {}, {}
        for i, vid in enumerate(vids):
            async def sub(f, m, i=i, vid=vid):
                await progress((i + f) / len(vids) * 0.9, f"[{vid}] {m}")
            try:
                info = await st.ts.build_series(vid, region, start, end, progress=sub)
                analyses[vid] = await pipeline.cached_analysis(st, info["series_id"])
                analyses[vid]["series_id"] = info["series_id"]
            except Exception as exc:  # noqa: BLE001 - a failing variable must not sink the scan
                failures[vid] = getattr(exc, "message", str(exc))
        out = rank_and_cohere(analyses, body.alpha) if analyses else {"ranking": [], "coherence": []}
        for r in out["ranking"]:
            r["series_id"] = analyses[r["variable_id"]]["series_id"]
        out["failed"] = failures
        return _clean(out)

    jid = st.jobs.submit("scan", body.model_dump(), job)
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}", "variables": vids}


@router.post("/insights", tags=["analysis"])
async def insights(request: Request, body: InsightsRequest):
    return await pipeline.cached_insights(S(request), body.series_id, which=body.which, alpha=body.alpha,
                                          forecast_horizon=body.forecast_horizon,
                                          triangle_min_years=body.triangle_min_years,
                                          min_segment_years=body.min_segment_years)


@router.post("/compare", tags=["analysis"])
async def compare(request: Request, body: CompareRequest):
    st = S(request)
    if body.mode == "product_agreement":
        if len(body.series_ids) != 2:
            raise InvalidRequest("product_agreement compares exactly two series")
        a, b = (st.store.load(s) for s in body.series_ids)
        return _clean(await run_in_threadpool(product_agreement, a, b, body.alpha))
    results = [await pipeline.cached_analysis(st, sid, alpha=body.alpha, include_series=False) for sid in body.series_ids]
    units = {r.get("variable_id") for r in results}
    out = compare_regions(results, body.alpha)
    if len(units) > 1:
        out["warning"] = "Series are different variables; regional comparison assumes the same variable."
    return _clean(out)


@router.post("/drivers", tags=["analysis"])
async def drivers(request: Request, body: DriversRequest):
    st = S(request)
    tgt = st.store.load(body.target_series_id)
    drv = [st.store.load(s) for s in body.driver_series_ids]
    return _clean(await run_in_threadpool(driver_analysis, tgt, drv, max_lag=body.max_lag, alpha=body.alpha))


@router.post("/trendmap", status_code=202, tags=["analysis"])
async def trendmap(request: Request, body: TrendMapRequest):
    st = S(request)
    v = st.catalog.get(body.variable_id)
    if not (v.get("fallback") or {}).get("concept_id"):
        raise InvalidRequest(f"{v['name']} has no monthly gridded collection for trend maps")
    region = parse_geometry(body.geometry)
    start, end = parse_date(body.start), parse_date(body.end, end=True)

    async def job(progress):
        times, cube, lat, lon, units, prov = await st.ts.connectors["opendap"].fetch_cube(
            FetchRequest(v, region, start, end), progress)
        months = pd.DatetimeIndex(times).month.to_numpy()
        res = await run_in_threadpool(cube_trends, cube, months, lat, lon, alpha=body.alpha)
        res.update({"variable_id": v["id"], "units": units, "provenance": prov.to_dict(),
                    "period": [str(pd.Timestamp(times[0]).date()), str(pd.Timestamp(times[-1]).date())]})
        return _clean(res)

    jid = st.jobs.submit("trendmap", body.model_dump(), job)
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}"}


@router.post("/trendmap/upload", tags=["analysis"])
async def trendmap_upload(request: Request, file: UploadFile = File(...), variable: str = Form(...),
                          alpha: float = Form(0.05)):
    """Per-pixel trends for a monthly netCDF you already have (e.g. downloaded from Giovanni)."""
    from ..timeseries.gridded import open_many, to_cube
    raw = await file.read()
    if len(raw) > 200 * 1024 * 1024:
        raise InvalidRequest("netCDF larger than 200 MB")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "upload.nc"
        p.write_bytes(raw)
        ds = open_many([p])
        times, cube, lat, lon = to_cube(ds, variable)
        months = pd.DatetimeIndex(times).month.to_numpy()
        res = await run_in_threadpool(cube_trends, cube, months, lat, lon, alpha=alpha)
    return _clean(res)


# ===================================================================== investigation & demos
@router.post("/investigate", status_code=202, tags=["investigate"])
async def investigate(request: Request, body: InvestigateRequest):
    st = S(request)
    if body.question:
        g = st.ai.guard(body.question)
        if not g["on_topic"]:
            from ..ai.guard import REFUSAL
            return ORJSONResponse({"on_topic": False, "message": REFUSAL, "guard": g}, status_code=200)

    async def job(progress):
        return await pipeline.investigate(st, question=body.question, variable_id=body.variable_id,
                                          geometry=body.geometry, start=body.start, end=body.end,
                                          insights=body.insights, explain=body.explain,
                                          max_regions=body.max_regions, progress=progress)

    jid = st.jobs.submit("investigate", body.model_dump(), job)
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}"}


@router.get("/demos", tags=["investigate"])
async def demos(request: Request):
    return {"demos": pipeline.demo_list(S(request), DEMOS)}


@router.post("/demos/{demo_id}/run", status_code=202, tags=["investigate"])
async def run_demo(request: Request, demo_id: str):
    st = S(request)
    demo = next((d for d in DEMOS if d["id"] == demo_id), None)
    if not demo:
        raise NotFound(f"demo {demo_id} not found")

    async def job(progress):
        return await pipeline.run_demo(st, demo, progress)

    jid = st.jobs.submit("demo", {"demo_id": demo_id}, job)
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}"}


# ===================================================================== offline AI
@router.get("/ai/status", tags=["ai"])
async def ai_status(request: Request):
    return await S(request).llm.status(force=True)


@router.post("/ai/guard", tags=["ai"])
async def ai_guard(request: Request, body: TextRequest):
    return S(request).ai.guard(body.question)


@router.post("/ai/plan", tags=["ai"])
async def ai_plan(request: Request, body: TextRequest):
    return await S(request).ai.plan(body.question)


@router.post("/ai/ask", tags=["ai"])
async def ai_ask(request: Request, body: TextRequest):
    return await S(request).ai.ask(body.question)


@router.post("/ai/explain", tags=["ai"])
async def ai_explain(request: Request, body: ExplainRequest):
    st = S(request)
    an = await pipeline.cached_analysis(st, body.series_id, include_series=False)
    ins = await pipeline.cached_insights(st, body.series_id) if body.include_insights else None
    entry = None
    if an.get("variable_id"):
        try:
            entry = st.catalog.get(an["variable_id"])
        except NotFound:
            entry = None
    return await st.ai.explain(an, ins, entry)
