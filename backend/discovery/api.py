"""/api/discovery: autonomous sweep for verified, not-yet-published changes (same job + EventLog pattern as
/api/active-trends: POST -> 202 {job_id, events_url, stream_url}; GET result; per-finding notebook)."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Query, Request
from fastapi.responses import ORJSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from ..active.runner import EventLog, request_key
from ..analysis.engine import _clean
from ..core.errors import InvalidRequest, NotFound
from . import job as D
from .notebook import build_notebook

router = APIRouter(prefix="/api/discovery", tags=["discovery"], default_response_class=ORJSONResponse)
JOB_ID = re.compile(r"^j_[0-9a-f]{16}$")
FINDING_ID = re.compile(r"^f\d{1,3}$")


class DiscoveryRequest(BaseModel):
    prompt: str | None = Field(None, max_length=500, examples=["find unreported changes in South Asia monsoon"],
                               description="free text; region, variables and years are parsed by the deterministic planner")
    geometry: dict | None = Field(None, description="GeoJSON Point/Polygon or {type:'BBox', bbox:[w,s,e,n]}")
    bbox: list[float] | None = Field(None, min_length=4, max_length=4, description="[west, south, east, north]")
    region_name: str | None = Field(None, max_length=120)
    criteria: list[str] | None = Field(None, max_length=12, description="ids from GET /api/criteria")
    variables: list[str] | None = Field(None, max_length=12, description="catalog ids; mapped to their criteria")
    start_year: int | None = Field(None, ge=1950, le=2100)
    end_year: int | None = Field(None, ge=1950, le=2100)
    max_findings: int = Field(3, ge=1, le=8)
    time_budget_s: int = Field(D.DEFAULT_BUDGET_S, ge=30, le=1200)
    alpha: float = Field(0.05, gt=0, lt=0.5)
    prefer_nasa: bool = Field(True, description="verify with NASA products (Giovanni) when a token exists")
    ai_prose: bool = Field(True, description="local-LLM student summary, kept only if number-checked")
    news: bool = True
    preprints: bool = True


def _st(request: Request):
    return request.app.state.etd


def _urls(jid: str) -> dict:
    return {"status_url": f"/api/discovery/{jid}", "events_url": f"/api/discovery/{jid}/events",
            "stream_url": f"/api/discovery/{jid}/stream"}


@router.post("", status_code=202)
async def start_discovery(request: Request, body: DiscoveryRequest):
    """Scan -> keep what's real (checks + BEAST) -> check what's known (literature, preprints, news) -> flag the
    gaps -> write it up (drivers, simulated outlook, notebook). Findings stream as `finding` events."""
    st = _st(request)
    data = body.model_dump()
    if not (data.get("prompt") or "").strip():
        data["prompt"] = None
    key = request_key(data)
    jid = D.INFLIGHT.get(key)
    if jid and (st.db.get_job(jid) or {}).get("status") in ("queued", "fetching", "processing"):
        return {"job_id": jid, "reused": True, **_urls(jid)}
    plan = D.make_plan(st, data)
    if not plan["sweeps"] and not plan["direct"]:
        raise InvalidRequest("Nothing to scan for this request", detail={"skipped": plan["skipped"]})
    log = EventLog()

    async def job(progress):
        try:
            out = await D.run(st, log, progress, plan, max_findings=body.max_findings, budget_s=body.time_budget_s,
                              alpha=body.alpha, ai_prose=body.ai_prose, news=body.news, preprints=body.preprints)
        except Exception as exc:
            await log.emit("error", message=getattr(exc, "message", str(exc)))
            raise
        finally:
            D.INFLIGHT.pop(key, None)
        for f in out["findings"]:
            f["notebook_url"] = f"/api/discovery/{jid_box[0]}/notebook/{f['finding_id']}"
        return _clean(out)

    jid_box: list[str] = []
    jid = st.jobs.submit("discovery", data, job)
    jid_box.append(jid)
    D.register(jid, log)
    D.INFLIGHT[key] = jid
    return {"job_id": jid, "reused": False, "plan": D.plan_view(plan), "time_budget_s": body.time_budget_s,
            **_urls(jid)}


def _log(jid: str) -> EventLog:
    log = D.LOGS.get(jid)
    if log is None:
        raise NotFound(f"No live event log for discovery job {jid!r} (the finished result stays at "
                       f"/api/discovery/{jid})")
    return log


@router.get("/{job_id}")
async def get_discovery(request: Request, job_id: str, wait: float = Query(0, ge=0, le=30)):
    st = _st(request)
    j = await st.jobs.wait(job_id, wait) if wait else st.db.get_job(job_id)
    if not j or j.get("kind") != "discovery":
        raise NotFound(f"discovery job {job_id} not found")
    return {"job_id": j["job_id"], "status": j["status"], "progress": j["progress"], "message": j["message"],
            "result": j.get("result"), "error": j.get("error"), "created_at": j["created_at"],
            "updated_at": j["updated_at"]}


@router.get("/{job_id}/events")
async def discovery_events(job_id: str, after: int = Query(0, ge=0), wait: float = Query(0, ge=0, le=30)):
    log = _log(job_id)
    ev = await log.wait(after, wait)
    return {"events": _clean(ev), "next": after + len(ev), "done": log.done}


@router.get("/{job_id}/stream")
async def discovery_stream(job_id: str, after: int = Query(0, ge=0)):
    log = _log(job_id)

    async def gen():
        i = after
        while True:
            ev = await log.wait(i, 15)
            for e in ev:
                yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(_clean(e), default=str)}\n\n"
            i += len(ev)
            if log.done and i >= len(log.events):
                return
            if not ev:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/{job_id}/notebook/{finding_id}")
async def discovery_notebook(request: Request, job_id: str, finding_id: str):
    """A reproducible Jupyter notebook (.ipynb) that re-fetches the data through this API and re-runs each step."""
    if not JOB_ID.match(job_id) or not FINDING_ID.match(finding_id):
        raise NotFound("Unknown job or finding id")
    j = _st(request).db.get_job(job_id)
    if not j or j.get("kind") != "discovery" or j.get("status") != "done":
        raise NotFound(f"No finished discovery job {job_id}")
    f = next((x for x in (j.get("result") or {}).get("findings", []) if x["finding_id"] == finding_id), None)
    if f is None:
        raise NotFound(f"Finding {finding_id} not in job {job_id}")
    nb = build_notebook(f, str(request.base_url), job_id)
    return Response(json.dumps(nb, indent=1, ensure_ascii=False), media_type="application/x-ipynb+json",
                    headers={"Content-Disposition": f'attachment; filename="discovery_{job_id}_{finding_id}.ipynb"'})
