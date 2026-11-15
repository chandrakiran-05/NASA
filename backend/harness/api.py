"""GET /api/harness (what runs each pipeline stage, config without secrets) and POST /api/harness/probe."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from ..ai import prompts
from ..core.errors import InvalidRequest
from . import config as hc
from .models import probe

router = APIRouter(prefix="/api/harness", tags=["harness"])

ACTIVE: dict | None = None        # set by `trend-harness serve`: {"config": HarnessConfig, "path": str | None}

# model: what the local model may do at this stage ("none" = the model never touches it)
STAGES = [
    {"id": "plan", "name": "Question to plan", "component": "backend/ai/assistant.py + guard.py",
     "model": "may suggest variable, place and period when the offline planner cannot; the catalog and "
              "guard decide what is accepted"},
    {"id": "data", "name": "Data fetch", "component": "backend/timeseries (Giovanni, AppEEARS, NOAA NCEI, ERDDAP, ...)",
     "model": "none"},
    {"id": "engine", "name": "Trend tests", "component": "backend/analysis (OLS with autocorrelation correction, "
                                                         "Mann-Kendall family, Sen's slope, Trend Court)",
     "model": "none"},
    {"id": "gate", "name": "BEAST + PELT gate", "component": "backend/active (Rbeast change points checked by PELT, "
                                                             "calibrated active-trend label)",
     "model": "none"},
    {"id": "report", "name": "Report", "component": "backend/report/builder.py (deterministic text from computed numbers)",
     "model": "none"},
    {"id": "wording", "name": "Wording", "component": "local model, sections listed in pipeline.rewrite_sections",
     "model": "may rewrite wording only, from a FACTS object"},
    {"id": "verify", "name": "Number check", "component": "backend/ai/verify.py verify_text (+ honest-wording guard)",
     "model": "none: rejected text falls back to the template"},
    {"id": "deep_review", "name": "Deep review (optional)", "component": "AirLLM, layer by layer from disk",
     "model": "advisory note only; never changes a verdict"},
]
PROMPTS = sorted(n for n in dir(prompts) if n.isupper() and isinstance(getattr(prompts, n), str)) + \
    ["report.builder.REWRITE_INSTRUCTIONS", "harness.models.PROBE_INSTRUCTIONS"]


def _current(st) -> tuple[hc.HarnessConfig, str]:
    if ACTIVE:
        return ACTIVE["config"], ACTIVE["path"] or "harness defaults (no harness.toml)"
    return hc.from_settings(st.settings), ".env (started without trend-harness serve; harness.toml not applied)"


@router.get("")
async def harness_info(request: Request):
    from ..report import builder
    st = request.app.state.etd
    cfg, source = _current(st)
    live, deep = await asyncio.gather(st.llm.status(), st.deep.status())
    return {"config": hc.redacted(cfg, st.settings), "source": source,
            "model_status": {"live": live, "deep": deep}, "stages": STAGES, "prompts": PROMPTS,
            "rewrite_sections_active": list(builder.REWRITE_IDS),
            "limit": "The model writes and plans; it never computes a number or decides a verdict."}


@router.post("/probe")
async def harness_probe(request: Request, body: dict | None = None):
    """Live tier: answers within `timeout_s` (default 90). Deep tier (AirLLM, minutes): returns a job."""
    st = request.app.state.etd
    body = body or {}
    tier = body.get("tier", "live")
    if tier == "deep":
        if not st.deep.enabled:
            raise InvalidRequest("Deep tier is off (DEEP_LLM_PROVIDER=none / deep.provider = \"none\")")

        async def job(progress):
            await progress(0.05, "Deep model is writing (seconds per token)")
            return await probe(st.deep)
        jid = st.jobs.submit("harness_probe", {"tier": "deep"}, job)
        return {"job_id": jid, "status_url": f"/api/jobs/{jid}"}
    if tier != "live":
        raise InvalidRequest("tier must be 'live' or 'deep'")
    t = body.get("timeout_s", 90)
    if not isinstance(t, (int, float)) or not 1 <= t <= 600:
        raise InvalidRequest("timeout_s must be a number from 1 to 600")
    try:
        return await asyncio.wait_for(probe(st.llm), t)
    except TimeoutError:
        return {"tier": "live", "provider": st.llm.provider, "model": st.llm.model, "verdict": "fail",
                "reason": f"no answer within {t:g} s"}
