"""Reusable orchestration: analysis with result caching, and the one-shot investigation
(question -> plan -> fetch -> analyze -> insights -> explanation, plus regional comparison)."""
from __future__ import annotations

import asyncio
from datetime import date

from starlette.concurrency import run_in_threadpool

from ..analysis.engine import analyze_series
from ..core.errors import InsufficientData, InvalidRequest
from ..core.geometry import parse_geometry
from ..insights.compare import compare_regions
from ..insights.engine import ALL_INSIGHTS, run_insights
from ..timeseries.service import parse_date
from .state import AppState


async def cached_analysis(st: AppState, series_id: str, *, alpha: float = 0.05, method: str = "stl",
                          mk_variant: str = "auto", include_series: bool = True) -> dict:
    params = {"alpha": alpha, "method": method, "mk": mk_variant, "series": include_series,
              "min_months": st.settings.min_months_for_test}
    key = st.result_key("analysis", series_id, params)
    hit = st.db.get_result(key)
    if hit:
        return hit
    ms = st.store.load(series_id)
    res = await run_in_threadpool(analyze_series, ms, alpha=alpha, deseasonalize_method=method,
                                  mk_variant=mk_variant, min_months=st.settings.min_months_for_test,
                                  include_series=include_series)
    st.db.put_result(key, series_id, "analysis", params, res)
    return res


async def cached_novelty(st: AppState, kind: str, series_id: str, fn, params: dict) -> dict:
    """Generic cached runner for the novelty modules (court, integrity, clock, nulls)."""
    key = st.result_key(kind, series_id, params)
    hit = st.db.get_result(key)
    if hit:
        return hit
    from ..analysis.engine import _clean
    ms = st.store.load(series_id)
    res = _clean(await run_in_threadpool(fn, ms))
    st.db.put_result(key, series_id, kind, params, res)
    return res


async def cached_insights(st: AppState, series_id: str, *, which=ALL_INSIGHTS, alpha: float = 0.05,
                          forecast_horizon: int = 60, triangle_min_years: int = 10,
                          min_segment_years: float = 4.0) -> dict:
    params = {"which": sorted(which), "alpha": alpha, "h": forecast_horizon, "tri": triangle_min_years,
              "seg": min_segment_years}
    key = st.result_key("insights", series_id, params)
    hit = st.db.get_result(key)
    if hit:
        return hit
    ms = st.store.load(series_id)
    if ms.n_valid < 24:
        raise InsufficientData(f"Only {ms.n_valid} valid months; insights need at least 24")
    res = await run_in_threadpool(run_insights, ms, which=tuple(which), alpha=alpha,
                                  forecast_horizon=forecast_horizon, triangle_min_years=triangle_min_years,
                                  min_segment_years=min_segment_years)
    st.db.put_result(key, series_id, "insights", params, res)
    return res


async def investigate(st: AppState, *, question: str | None, variable_id: str | None, geometry: dict | None,
                      start: str | None, end: str | None, insights: list[str], explain: bool, max_regions: int,
                      progress) -> dict:
    report: dict = {}
    targets: list[dict] = []
    if question:
        await progress(0.02, "Understanding the question")
        plan = await st.ai.plan(question)
        report["plan"] = plan
        if not plan.get("on_topic"):
            return {"on_topic": False, "message": plan.get("message"), "plan": plan}
        vid = variable_id or (plan["variables"][0]["id"] if plan["variables"] else None)
        regions = [r["geometry"] for r in plan["regions"]][:max_regions]
        if geometry:
            regions = [geometry]
        if not vid or not regions:
            return {"on_topic": True, "needs_user_input": plan["needs_user_input"], "plan": plan,
                    "message": "Please choose " + " and ".join(plan["needs_user_input"]) + " to continue."}
        s0 = start or plan["period"]["start"]
        s1 = end or plan["period"]["end"]
        if not plan["wishes"].get("compare"):
            regions = regions[:1]
        targets = [{"variable_id": vid, "geometry": g, "start": s0, "end": s1} for g in regions]
    else:
        if not (variable_id and geometry and start and end):
            raise InvalidRequest("Give either a question, or variable_id + geometry + start + end")
        targets = [{"variable_id": variable_id, "geometry": geometry, "start": start, "end": end}]

    results = []
    n = len(targets)
    for i, tg in enumerate(targets):
        region = parse_geometry(tg["geometry"])
        base = 0.05 + 0.75 * i / n

        async def sub(frac, msg, base=base):
            await progress(base + 0.75 * frac / n, f"[{region.name or 'region'}] {msg}")

        info = await st.ts.build_series(tg["variable_id"], region, parse_date(tg["start"]),
                                        parse_date(tg["end"], end=True), progress=sub)
        sid = info["series_id"]
        await progress(base + 0.7 / n, "Running trend tests")
        an = await cached_analysis(st, sid)
        ins = None
        if insights:
            ins = await cached_insights(st, sid, which=insights)
        results.append({"series": info, "analysis": an, "insights": ins})
    report["results"] = results
    if len(results) > 1:
        report["comparison"] = compare_regions([r["analysis"] for r in results])
    intents = (report.get("plan") or {}).get("intents") or ["what"]
    drivers = None
    if "why" in intents:
        await progress(0.82, "Testing suspect drivers (PCMCI+)")
        drivers = await why_drivers(st, targets[0], results[0]["series"]["series_id"])
        report["why"] = drivers
    report["answer"] = compose_answer(intents, results[0], drivers)
    if explain:
        await progress(0.9, "Writing the explanation")
        entry = st.catalog.get(targets[0]["variable_id"])
        report["explanation"] = await st.ai.explain(results[0]["analysis"], results[0]["insights"], entry,
                                                    drivers=drivers, intents=intents)
    report["on_topic"] = True
    return report


async def why_drivers(st: AppState, target: dict, target_series_id: str) -> dict:
    """WHY: pre-registered suspects (textbook + local AI, no data) -> fetch them -> PCMCI+ decides."""
    from ..insights.causal import causal_screen, judge_suspects
    region = parse_geometry(target["geometry"])
    suspects = await st.ai.suspects(target["variable_id"], region.name)
    if not suspects:
        return {"status": "no_suspects", "suspects": [], "protocol": "suspects were fixed before any data was fetched; none are defined for this variable",
                "plain_language": "No driver hypotheses are defined for this variable yet."}
    tgt = st.store.load(target_series_id)
    drv, notes = [], []
    for s in suspects:
        try:
            info = await st.ts.build_series(s["driver_id"], region, parse_date(target["start"]),
                                            parse_date(target["end"], end=True))
            d = st.store.load(info["series_id"])
            d.variable_id = s["driver_id"]
            drv.append(d)
        except Exception as exc:  # noqa: BLE001 - a missing driver must not sink the investigation
            notes.append(f"{s['driver_id']}: {type(exc).__name__}")
    screen = await run_in_threadpool(causal_screen, tgt, drv) if drv else {"status": "no_drivers"}
    judged = judge_suspects(screen, suspects)
    from ..analysis.engine import _clean
    return _clean({"status": screen.get("status"), **judged, "screen": screen, "fetch_notes": notes,
                   "protocol": "suspects were fixed before any data was fetched; PCMCI+ decided each one"})


def compose_answer(intents: list[str], result: dict, drivers: dict | None) -> dict:
    """Direct answer per question type, built only from module outputs (no new numbers)."""
    an, ins = result.get("analysis") or {}, result.get("insights") or {}
    v = an.get("verdict", {})
    sections = [{"intent": "what", "question": "Is it changing, by how much, and is it significant?",
                 "answer": v.get("plain_language"), "source": "trend tests (OLS AR1-adjusted, Mann-Kendall, Sen)"}]
    if "when" in intents or "onset" in ins:
        o = ins.get("onset") or {}
        if o.get("plain_language"):
            sections.append({"intent": "when", "question": "When did it change, and how sure are we?",
                             "answer": o["plain_language"], "source": "calibrated BEAST (Zhao et al. 2019)"})
    if "why" in intents and drivers:
        sections.append({"intent": "why", "question": "Which processes is it associated with?",
                         "answer": drivers.get("plain_language"), "source": "pre-registered suspects + PCMCI+ (Runge 2019)"})
    if "how_long" in intents or "detectability" in ins:
        parts = [(ins.get(k) or {}).get("plain_language") for k in ("emergence", "detectability")]
        parts = [p for p in parts if p]
        if parts:
            sections.append({"intent": "how_long", "question": "Has it emerged from natural noise? How long until we know?",
                             "answer": " ".join(parts), "source": "time of emergence (Hawkins & Sutton) + Weatherhead 1998"})
    if "forecast" in intents and (ins.get("forecast") or {}).get("plain_language"):
        sections.append({"intent": "forecast", "question": "Where is it heading if nothing changes?",
                         "answer": ins["forecast"]["plain_language"],
                         "source": "statistical extrapolation, not a climate projection"})
    order = {k: i for i, k in enumerate(["what", "when", "why", "how_long", "forecast"])}
    sections.sort(key=lambda s: order.get(s["intent"], 9))
    asked = [s for s in sections if s["intent"] in intents and s["intent"] != "what"]
    headline = (asked[0]["answer"] if asked else sections[0]["answer"]) or ""
    return {"intents": intents, "headline": headline, "sections": sections}


def demo_list(st: AppState, demos: list[dict]) -> list[dict]:
    out = []
    for d in demos:
        reqs = d.get("compare") or [d["request"]]
        cached = []
        for r in reqs:
            try:
                v = st.catalog.get(r["variable_id"])
                region = parse_geometry(r["geometry"])
                rh = st.ts.request_hash(v, region, parse_date(r["start"]), parse_date(r["end"], end=True), {})
                from ..storage.series_store import make_series_id
                cached.append(st.store.exists(make_series_id(rh)))
            except Exception:  # noqa: BLE001
                cached.append(False)
        out.append({k: d[k] for k in ("id", "title", "story", "teaches")} | {"cached": all(cached), "n_series": len(reqs)})
    return out


async def run_demo(st: AppState, demo: dict, progress) -> dict:
    if demo.get("compare"):
        res = []
        for i, r in enumerate(demo["compare"]):
            region = parse_geometry(r["geometry"])
            info = await st.ts.build_series(r["variable_id"], region, parse_date(r["start"]),
                                            parse_date(r["end"], end=True))
            res.append({"series": info, "analysis": await cached_analysis(st, info["series_id"])})
            await progress((i + 1) / len(demo["compare"]), f"series {i + 1} ready")
        return {"demo": demo["id"], "results": res, "comparison": compare_regions([r["analysis"] for r in res])}
    r = demo["request"]
    rep = await investigate(st, question=None, variable_id=r["variable_id"], geometry=r["geometry"], start=r["start"],
                            end=r["end"], insights=list(ALL_INSIGHTS), explain=True, max_regions=1, progress=progress)
    rep["demo"] = demo["id"]
    return rep


def today_str() -> str:
    return date.today().isoformat()


__all__ = ["cached_analysis", "cached_insights", "investigate", "demo_list", "run_demo", "asyncio"]
