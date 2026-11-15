"""REST endpoints (architecture §2 plus insights / AI / investigation extensions)."""
from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import ORJSONResponse, PlainTextResponse, StreamingResponse
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
from ..active import runner as active
from .schemas import (ActiveTrendsRequest, AnalyzeRequest, CompareRequest, DriversRequest, ExplainRequest, InsightsRequest,
                      InvestigateRequest, NullsRequest, ScanRequest, TextRequest, TimeseriesRequest,
                      TrendMapRequest, UploadSeries)
from .state import AppState

router = APIRouter(prefix="/api", default_response_class=ORJSONResponse)
DEMOS = json.loads((CATALOG_DATA / "demos.json").read_text(encoding="utf-8"))["demos"]


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
    try:
        ms = MonthlySeries.from_arrays(body.time, [np.nan if v is None else v for v in body.value], units=body.units,
                                       provenance=Provenance(source_api="user_upload", variable=body.label or "value",
                                                             geometry={}), label=body.label)
    except ValueError as exc:                          # unparseable dates
        raise InvalidRequest(f"Could not read the dates: {exc}") from exc
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
    try:
        df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    except ValueError as exc:                          # pandas ParserError/EmptyDataError are ValueErrors
        raise InvalidRequest(f"Could not read the CSV: {exc}") from exc
    tcol = df.columns[0]
    vcol = next((c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])), None)
    if vcol is None:
        raise InvalidRequest("No numeric value column found")
    body = UploadSeries(time=df[tcol].astype(str).tolist(), value=[None if pd.isna(v) else float(v) for v in df[vcol]],
                        units=units, label=label or f"{file.filename}:{vcol}")
    return await upload_series(request, body)


@router.get("/export/{series_id}", tags=["timeseries"])
async def export_series(request: Request, series_id: str,
                        format: str = Query("csv", pattern="^(csv|json|waterml2|cuahsi_csv)$")):
    st = S(request)
    ms = st.store.load(series_id)
    if format in ("waterml2", "cuahsi_csv"):          # CUAHSI HIS / HydroShare-compatible outputs
        from ..timeseries.waterml import to_cuahsi_csv, to_waterml2
        v = st.catalog.variables.get(ms.variable_id or "")
        if format == "waterml2":
            return PlainTextResponse(to_waterml2(ms, series_id=series_id, variable=v), media_type="application/xml",
                                     headers={"Content-Disposition": f'attachment; filename="{series_id}.wml2.xml"'})
        return PlainTextResponse(to_cuahsi_csv(ms, series_id=series_id, variable=v), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{series_id}_cuahsi.csv"'})
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


@router.get("/analyze/{series_id}/onset", tags=["forensics"])
async def onset_endpoint(request: Request, series_id: str, alpha: float = Query(0.05, gt=0, lt=0.5),
                         n_surrogates: int = Query(49, ge=19, le=199)):
    """Trend Forensics WHEN: calibrated BEAST change dating (events, probability, 90% interval, seams)."""
    from ..insights.onset import change_onset
    from ..novelty.integrity import events_for
    return await pipeline.cached_novelty(
        S(request), "onset", series_id,
        lambda ms: change_onset(ms, seams=events_for(ms), alpha=alpha, n_surrogates=n_surrogates),
        {"alpha": alpha, "k": n_surrogates})


@router.post("/ai/suspects", tags=["forensics"])
async def ai_suspects(request: Request, body: dict):
    """Trend Forensics WHY, step 1: pre-registered driver hypotheses (no data seen)."""
    vid = body.get("variable_id")
    if not vid:
        raise InvalidRequest("variable_id is required")
    st = S(request)
    st.catalog.get(vid)
    return {"variable_id": vid, "suspects": await st.ai.suspects(vid, body.get("region_name")),
            "protocol": "hypotheses fixed before data; test them with POST /api/drivers method=pcmci"}


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
    if body.method == "pcmci":
        from ..insights.causal import causal_screen, judge_suspects
        res = await run_in_threadpool(causal_screen, tgt, drv, tau_max=min(body.max_lag, 6), alpha=body.alpha)
        if body.suspects:
            res["judged"] = judge_suspects(res, body.suspects)
        return _clean(res)
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
        with open_many([p]) as ds:  # closed before cleanup: Windows cannot delete an open file
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
    """With `conversation_id`, a follow-up ("what about Kerala?") inherits the variable, place and years it
    does not name from the conversation's last plan; `context.inherited` and `message` say what was kept."""
    from ..ai.memory import new_id
    cid = body.conversation_id or new_id()
    out = await S(request).ai.plan(body.question, conversation_id=cid)
    out["conversation_id"] = cid
    return out


@router.post("/ai/ask", tags=["ai"])
async def ai_ask(request: Request, body: TextRequest):
    """With `conversation_id`, the last few turns are given to the local LLM as context (answers are still
    verified) and missing variable / place / years are inherited from the conversation."""
    from ..ai.memory import new_id
    cid = body.conversation_id or new_id()
    out = await S(request).ai.ask(body.question, conversation_id=cid)
    out["conversation_id"] = cid
    return out


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


# ===================================================================== active trends (live, verified)
@router.get("/criteria", tags=["active"])
async def criteria(request: Request):
    """The 28 investigation criteria, their catalog variables and whether they can be trend-tested."""
    return {"criteria": active.criteria_view(S(request).catalog)}


@router.post("/active-trends", status_code=202, tags=["active"])
async def active_trends(request: Request, body: ActiveTrendsRequest):
    """Which variables are changing NOW? Detect -> independent checks (concurrent) -> BEAST -> verdict.

    Follow progress live with GET /api/active-trends/{job_id}/events (long-poll) or /stream (SSE).
    Identical requests reuse the running job, so a client may start one while the user is still typing."""
    st = S(request)
    key = active.request_key(body.model_dump())
    jid = active.INFLIGHT.get(key)
    if jid and (st.db.get_job(jid) or {}).get("status") in ("queued", "fetching", "processing"):
        return {"job_id": jid, "reused": True, **_active_urls(jid)}
    start, end = active.parse_period(body.start, body.end)
    region = None
    if body.series_ids:
        items, skipped = [{"variable_id": None, "series_id": s} for s in body.series_ids], []
        for s in body.series_ids:
            st.store.load(s)                                   # 404 early for unknown ids
    else:
        if not (body.geometry and start and end):
            raise InvalidRequest("geometry, start and end are required unless series_ids are given")
        region = parse_geometry(body.geometry)
        items, skipped = active.plan(st.catalog, region, start, end, criteria=body.criteria,
                                     variable_ids=body.variable_ids, per_criterion=body.per_criterion,
                                     options=body.options)
        if not items:
            raise InvalidRequest("No variable can be trend-tested for this region and period", detail={"skipped": skipped})
    log = active.EventLog()

    async def job(progress):
        try:
            out = await active.run(st, log, progress, items=items, region=region, start=start, end=end,
                                   alpha=body.alpha, ai_review=body.ai_review, options=body.options,
                                   research=body.research, region_name=body.region_name)
        except Exception as exc:
            await log.emit("error", message=getattr(exc, "message", str(exc)))
            raise
        finally:
            active.INFLIGHT.pop(key, None)     # a retry after this point runs again (results are cached)
        out["skipped"] = skipped
        return _clean(out)

    jid = st.jobs.submit("active_trends", body.model_dump(), job)
    active.register(jid, log)
    active.INFLIGHT[key] = jid
    return {"job_id": jid, "reused": False, "variables": [i["variable_id"] or i["series_id"] for i in items],
            "skipped": skipped, **_active_urls(jid)}


def _active_urls(jid: str) -> dict:
    return {"status_url": f"/api/jobs/{jid}", "events_url": f"/api/active-trends/{jid}/events",
            "stream_url": f"/api/active-trends/{jid}/stream"}


def _log(jid: str) -> "active.EventLog":
    log = active.LOGS.get(jid)
    if log is None:
        raise NotFound(f"No live event log for job {jid!r} (finished results stay at /api/jobs/{jid})")
    return log


@router.get("/active-trends/{job_id}/events", tags=["active"])
async def active_events(job_id: str, after: int = Query(0, ge=0), wait: float = Query(0, ge=0, le=30)):
    """Events after sequence number `after`; waits up to `wait` seconds for new ones."""
    log = _log(job_id)
    ev = await log.wait(after, wait)
    return {"events": _clean(ev), "next": after + len(ev), "done": log.done}


@router.get("/active-trends/{job_id}/stream", tags=["active"])
async def active_stream(job_id: str, after: int = Query(0, ge=0)):
    """Server-Sent Events: one `data:` line per event; the stream ends after `done` or `error`."""
    log = _log(job_id)

    async def gen():
        i = after
        while True:
            ev = await log.wait(i, 15)
            for e in ev:
                yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(_clean(e))}\n\n"
            i += len(ev)
            if log.done and i >= len(log.events):
                return
            if not ev:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/active-trends/{job_id}/deep-review", status_code=202, tags=["active"])
async def active_deep_review(request: Request, job_id: str, top: int = Query(3, ge=1, le=5)):
    """Optional AirLLM deep reviewer on the top finished trends. Slow (minutes per trend on a 4 GB GPU),
    advisory only: it never changes a label. Events also go to the original job's stream if it is open."""
    st = S(request)
    if not st.deep.enabled:
        raise InvalidRequest("Deep AI tier is off (DEEP_LLM_PROVIDER=none); see GET /api/ai/hardware",
                             detail=await st.deep.status())
    j = st.db.get_job(job_id)
    if not j or j.get("kind") != "active_trends" or j.get("status") != "done":
        raise InvalidRequest("Run POST /api/active-trends first and wait until it is done")
    picks = [t for t in j["result"]["trends"] if t["verdict"]["label"] != "NOT VERIFIED"][:top]
    log = active.LOGS.get(job_id)

    async def job(progress):
        out = []
        for i, tr in enumerate(picks):
            await progress(i / max(len(picks), 1), f"Deep review of {tr['name']}")
            c = {**active.engine.check_llm_note(await active.review(st.deep, tr)), "check": "deep_review"}
            out.append({"variable_id": tr["variable_id"], **c})
            if log:
                await log.emit("deep_review", variable_id=tr["variable_id"], **c)
        return {"reviews": out, "model": (await st.deep.status()).get("model"),
                "limit": "Advisory AI opinion; the statistical verdicts above are unchanged."}

    jid = st.jobs.submit("deep_review", {"job_id": job_id, "top": top}, job)
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}", "trends": [t["variable_id"] for t in picks]}


@router.get("/ai/hardware", tags=["ai"])
async def ai_hardware(request: Request):
    """This machine's GPU/RAM/disk, and which live (Ollama) and deep (AirLLM) models fit it."""
    from ..core import hardware
    st = S(request)
    prof = await run_in_threadpool(hardware.probe, st.settings.deep_llm_layer_dir)
    rec = hardware.recommend(prof)
    prof.pop("disk_path", None)                   # keep local folder names out of the profile block
    return {"profile": prof, "recommendation": rec,
            "live": await st.llm.status(), "deep": await st.deep.status()}


# ===================================================================== research evidence (live literature)
@router.post("/research/evidence", tags=["research"])
async def research_evidence_endpoint(request: Request, body: dict):
    """Search recent literature (arXiv, OpenAlex, Springer Nature) for a variable/region/direction and report
    whether published studies agree. AI readings of abstracts are kept only if their quote is verbatim."""
    from ..research.evidence import research_evidence
    st = S(request)
    vid = body.get("variable_id")
    direction = body.get("direction")
    if not vid or direction not in ("rising", "falling"):
        raise InvalidRequest("variable_id and direction ('rising' or 'falling') are required")
    v = st.catalog.get(vid)
    age = body.get("max_age_years") or st.settings.research_max_age_years
    if not isinstance(age, int) or not 1 <= age <= 50:
        raise InvalidRequest("max_age_years must be a whole number from 1 to 50")
    return _clean(await research_evidence(
        st.http, st.llm, variable_id=vid, variable_name=v.get("name"), region_name=body.get("region_name"),
        direction=direction, max_age_years=age,
        per_source=st.settings.research_per_source, springer_key=st.settings.springer_api_key,
                    semantic_key=st.settings.semantic_scholar_api_key, ads_token=st.settings.ads_api_token))


# ===================================================================== chart-ready view (BEAST + PELT + local AI)
@router.get("/view/{series_id}", tags=["active"])
async def series_view(request: Request, series_id: str, alpha: float = Query(0.05, gt=0, lt=0.5),
                      explain: bool = True):
    """Everything to draw one series: observed + trend lines, BEAST ribbon and events, PELT breaks, and the
    local model's fact-checked explanation."""
    from ..active.view import build_view
    return _clean(await build_view(S(request), series_id, alpha=alpha, explain=explain))



@router.get("/research/methods", tags=["research"])
async def research_methods(request: Request, max_age_years: int = Query(10, ge=1, le=50)):
    """Recent papers on the methods behind the verdicts: Mann-Kendall, Sen, BEAST, PELT, change points."""
    from ..research.evidence import method_literature
    return _clean(await method_literature(S(request).http, max_age_years=max_age_years))


# ===================================================================== printable trend card (SVG, no dependencies)
@router.get("/view/{series_id}/card.svg", tags=["active"])
async def series_card(request: Request, series_id: str, alpha: float = Query(0.05, gt=0, lt=0.5)):
    """A one-page printable card: chart (observed, Sen line, BEAST change probability, BEAST/PELT markers),
    verdict, explanation and limits. Open in a browser and print."""
    from fastapi.responses import Response
    from ..active.card import card_svg
    from ..active.view import build_view
    v = await build_view(S(request), series_id, alpha=alpha)
    return Response(card_svg(_clean(v)), media_type="image/svg+xml",
                    headers={"Content-Disposition": f'inline; filename="{series_id}.svg"'})


# ===================================================================== student report (continuous, sectioned)
from pydantic import BaseModel as _BaseModel, Field as _Field  # noqa: E402


class ReportRequest(_BaseModel):
    question: str = _Field(..., min_length=3, max_length=500)
    start: str | None = _Field(None, description="YYYY-MM; default: from the question, else the last 20 full years")
    end: str | None = _Field(None, description="YYYY-MM")
    variable_id: str | None = None
    geometry: dict | None = None
    conversation_id: str | None = _Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]{1,64}$",
                                         description="follow-up memory (see /ai/plan); the result gets a "
                                                     "`conversation` block")
    refresh: bool = _Field(False, description="ignore the cached report for the same variables, region and period")


# job_id -> latest partial report (deterministic first, then AI wording / research section by section)
_REPORT_PARTIALS: dict[str, dict] = {}


@router.post("/report", status_code=202, tags=["investigate"])
async def report(request: Request, body: ReportRequest):
    """A full student report for one question. Poll /api/jobs/{job_id}; result:
    {question, plan, headline, sections[{id, title, kind, text, text_source, ai_status, data}], glossary, provenance,
    limits, ai{used, label, status: writing|done, pending[], research}, timing}.
    The deterministic report is ready long before the job ends: poll GET /api/report/{job_id}/partial and show
    it; sections with ai_status 'pending' get their AI wording (number-checked) later, one by one.
    Section ids in order: answer, data, series, how_much, is_it_real, when, seasons, map, context, limits.
    kind data shapes: table {columns[], rows[][]}; chart = /api/view object (+events, pelt_breaks for 'when');
    checks {verdict, why, checks[{check,status,text}], beast, court{stamp,...}, limit};
    bars {labels[12], values[], ci_low[], ci_high[], ci_excludes_zero[], units};
    map {lat[], lon[], slope_per_decade[][], significant[][], units, area_fraction_rising, area_fraction_falling,
    field_significance, n_cells, bbox, provenance, label:'exploratory'}; text {}."""
    st = S(request)
    g = st.ai.guard(body.question)
    if not g["on_topic"]:
        from ..ai.guard import REFUSAL
        raise InvalidRequest(REFUSAL, detail={"guard": g})
    from ..report import build_report

    cid = body.conversation_id
    start, end, variable_id, geometry = body.start, body.end, body.variable_id, body.geometry
    conv = None
    if cid and st.ai.memory.get_plan(cid):
        # fill what the follow-up leaves out from the conversation (deterministic; nothing is stored yet)
        ctx_plan = st.ai.apply_memory(st.ai._deterministic_plan(body.question), body.question, cid, remember=False)
        conv = ctx_plan["context"]
        inh = conv["inherited"]
        if "variable" in inh and not variable_id and ctx_plan.get("variables"):
            variable_id = ctx_plan["variables"][0].get("id")
        if "region" in inh and not geometry and ctx_plan.get("regions"):
            geometry = dict(ctx_plan["regions"][0].get("geometry") or {}) or None
            if geometry and ctx_plan["regions"][0].get("name"):
                geometry.setdefault("name", ctx_plan["regions"][0]["name"])
        if "period" in inh and not body.start and not body.end and conv.get("period"):
            start, end = ctx_plan["period"].get("start"), ctx_plan["period"].get("end")
        conv = {**conv, "message": ctx_plan.get("message")}

    async def job(progress):
        def on_partial(rep):
            _REPORT_PARTIALS[holder["id"]] = rep
        result = await build_report(st, question=body.question, start=start, end=end, variable_id=variable_id,
                                    geometry=geometry, progress=progress, on_partial=on_partial,
                                    refresh=body.refresh)
        if cid and isinstance(result, dict):
            st.ai.remember_report(cid, body.question, result)
            from ..ai.memory import summary_of
            result["conversation"] = {"conversation_id": cid, **(conv or {"inherited": []}),
                                      "summary": summary_of(st.ai.memory.get_plan(cid))}
        return result

    holder: dict = {}
    jid = st.jobs.submit("report", body.model_dump(), job)
    holder["id"] = jid
    while len(_REPORT_PARTIALS) > 32:
        _REPORT_PARTIALS.pop(next(iter(_REPORT_PARTIALS)))
    return {"job_id": jid, "status_url": f"/api/jobs/{jid}", "partial_url": f"/api/report/{jid}/partial"}


@router.get("/report/{job_id}/partial", tags=["investigate"])
async def report_partial(request: Request, job_id: str):
    """The report as far as it is built: `ready` turns true as soon as the deterministic report (every number,
    template text) exists; later polls carry AI-written sections as they pass the number check. When the job
    is done this is the final result."""
    st = S(request)
    j = st.db.get_job(job_id)
    if not j or j.get("kind") != "report":
        raise NotFound(f"report job {job_id} not found")
    rep = j.get("result") if j["status"] == "done" else _REPORT_PARTIALS.get(job_id)
    if j["status"] in ("done", "error"):
        _REPORT_PARTIALS.pop(job_id, None)
    return {"job_id": job_id, "status": j["status"], "progress": j["progress"], "message": j["message"],
            "ready": rep is not None, "report": rep, "error": j.get("error")}
