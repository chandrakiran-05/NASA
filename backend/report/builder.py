"""Student report: question -> plan -> keyless-aware fetch -> analysis, active-trend checks, BEAST/PELT dating,
per-month trends, per-grid-cell trend map -> ten sections of plain text.

Every number comes from the existing modules (analysis engine, active-trend engine, onset/BEAST, PELT,
cube_trends). Section text is first written deterministically from those numbers; the local LLM may then
rewrite each section for a 15-year-old, and its text is kept only if `verify_text` passes against that
section's facts (numbers traced, direction, significance, no causal words, no predictions).

Speed: the deterministic report is published first (`on_partial`), then the local AI rewrites only the
most-read sections one by one and published research is added; each step is published again. Independent
stages run concurrently, and whole reports are cached by (variables, region, period, alpha).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from starlette.concurrency import run_in_threadpool

from ..analysis.engine import _clean
from ..connectors.base import FetchRequest
from ..core.errors import InvalidRequest
from ..core.geometry import Region, parse_geometry
from ..timeseries.service import parse_date

SECTION_ORDER = ["answer", "data", "series", "how_much", "is_it_real", "when", "seasons", "map", "context", "limits"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MAP_HALF_BOX_DEG = 12.0
AI_LABEL = "AI-written, number-checked"

GLOSSARY = [
    {"term": "Monthly series", "meaning": "One number per month: the average of the quantity over the whole region."},
    {"term": "Deseasonalized", "meaning": "The usual seasonal cycle (for example hot summers, cool winters) is "
                                          "removed so only the slow change and the surprises remain."},
    {"term": "Trend per decade", "meaning": "How much the value changes in 10 years if it changes at a steady rate."},
    {"term": "Sen's slope", "meaning": "A robust trend rate: the median of the slopes between every pair of months, "
                                       "so a few extreme months cannot pull it much."},
    {"term": "95% confidence interval", "meaning": "The range of trend rates that fit the data; if it does not "
                                                   "include zero, a flat line fits the data badly."},
    {"term": "Mann-Kendall test", "meaning": "Checks whether later values tend to be higher (or lower) than "
                                             "earlier ones, without assuming a straight line."},
    {"term": "Standard deviation", "meaning": "The typical size of month-to-month ups and downs. Comparing the change "
                                              "with it shows whether the change is big compared with normal noise."},
    {"term": "BEAST", "meaning": "A Bayesian method that estimates when the trend changed and how likely each change is."},
    {"term": "PELT", "meaning": "A fast method that finds the best places to split the record into straight pieces; "
                                "used as an independent check on BEAST's dates."},
    {"term": "Field significance", "meaning": "When thousands of map cells are tested at once some look significant "
                                              "by luck; the Benjamini-Hochberg correction removes most of those."},
    {"term": "Trend Court", "meaning": "Several trend tests are run as 'jurors'; the stamp says SIGNIFICANT or NOT "
                                       "PROVEN using the test that fits the data best."},
    {"term": "Reanalysis", "meaning": "A weather model fed with millions of observations, giving complete maps with "
                                      "no gaps; it is model-based, not a direct measurement."},
]

FAMILY_CONTEXT = {
    "temperature": ("A change in near-surface air temperature is consistent with the global warming trend reported "
                    "by climate assessments, and regional factors such as land-use change, irrigation, cities and "
                    "air pollution (aerosols) are associated with local temperature differences."),
    "precipitation": ("Changes in rainfall are associated with shifts in monsoon circulation, ocean temperature "
                      "patterns such as El Niño and La Niña, and a warmer atmosphere that can hold more water vapour."),
    "soil_moisture": ("Soil moisture changes are consistent with changes in rainfall, temperature (evaporation) "
                      "and irrigation."),
    "humidity": ("Humidity changes are associated with changes in temperature and in the moisture carried by winds "
                 "from the ocean."),
    "sst": ("Ocean surface temperature changes are consistent with global ocean warming and are associated with "
            "natural cycles such as El Niño and the Pacific Decadal Oscillation."),
}


# ---------------------------------------------------------------- small helpers
def fmt(x, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:+.{nd}f}" if nd >= 0 else str(x)


def num(x, nd: int = 2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def short_name(v: dict) -> str:
    """'Air temperature near the ground, anywhere on Earth (NOAA ...)' -> 'air temperature near the ground'."""
    n = v["name"].split(" (")[0].split(",")[0].strip()
    return n[:1].lower() + n[1:]


def last_full_year() -> int:
    return date.today().year - 1


def resolve_period(plan: dict, start: str | None, end: str | None) -> tuple[str, str, str]:
    if start or end:
        y1 = last_full_year()
        return start or f"{y1 - 19}-01", end or f"{y1}-12", "chosen by you"
    per = plan.get("period") or {}
    if per.get("parsed_from") and per.get("start") and per.get("end"):
        return per["start"], per["end"], f"read from the question ('{per['parsed_from']}')"
    y1 = last_full_year()
    return f"{y1 - 19}-01", f"{y1}-12", "default: the last 20 full years"


def shift_period(st, cands: list[str], s0: str, s1: str) -> tuple[str, str, str] | None:
    """When the asked years end before any candidate dataset begins (no instruments or satellites then), use the
    earliest real record instead and say so. Returns (start, end, notice) or None when the period is usable."""
    from ..active.engine import MIN_YEARS
    starts = [int(st.catalog.variables[c]["coverage_start"][:4]) for c in cands
              if (st.catalog.variables[c].get("coverage_start") or "")[:4].isdigit()]
    if not starts:
        return None
    first = starts[0]                      # the dataset that will be used first (fallbacks start later or equal)
    if int(s1[:4]) - max(int(s0[:4]), first) + 1 >= MIN_YEARS:
        return None
    y1 = last_full_year()
    notice = (f"shifted: you asked for {s0[:4]}-{s1[:4]}, but no satellite or instrument record covers those years "
              f"(the earliest matching record here starts in {first}). Rain gauges and satellites did not exist "
              f"then; knowledge of that era comes from tree rings, cave deposits and historical documents, which "
              f"this tool does not analyse. Showing the earliest real record instead: {first}-{y1}")
    return f"{first}-01", f"{y1}-12", notice


def candidate_variables(st, plan: dict, variable_id: str | None) -> list[str]:
    """Planner's first choice, then the keyless/alternative variables of the same criterion, then the planner's others."""
    from ..active.runner import CRITERIA
    if variable_id:
        st.catalog.get(variable_id)
        first = [variable_id]
    else:
        first = [v["id"] for v in plan.get("variables") or []][:1]
    alts = [v for c in CRITERIA if first and first[0] in c["variables"] for v in c["variables"]]
    others = [v["id"] for v in plan.get("variables") or []] if not variable_id else []
    return [v for v in dict.fromkeys([*first, *alts, *others]) if v in st.catalog.variables]


def map_box(region: Region) -> tuple[Region, bool]:
    if region.is_point:
        lon, lat = region.point
        bb = (max(lon - MAP_HALF_BOX_DEG, -180.0), max(lat - MAP_HALF_BOX_DEG, -90.0),
              min(lon + MAP_HALF_BOX_DEG, 180.0), min(lat + MAP_HALF_BOX_DEG, 90.0))
        return Region("bbox", bb, name=f"box of about ±{MAP_HALF_BOX_DEG:.0f}° around {region.name or 'the point'}"), True
    return Region("bbox", tuple(region.bbox), name=region.name), False


def map_variable(st, vid: str) -> str | None:
    """The variable itself if it is a keyless ERDDAP grid, else a keyless ERDDAP grid of the same criterion."""
    from ..active.runner import CRITERIA
    v = st.catalog.variables.get(vid) or {}
    if v.get("source") == "erddap":
        return vid
    for c in CRITERIA:
        if vid in c["variables"]:
            for a in c["variables"]:
                if (st.catalog.variables.get(a) or {}).get("source") == "erddap":
                    return a
    return None


def seasonal_slopes(ms, alpha: float = 0.05) -> dict:
    from ..analysis.trend import sens_slope
    years = ms.time.year.to_numpy().astype(float)
    out = {"labels": MONTHS, "values": [], "ci_low": [], "ci_high": [], "ci_excludes_zero": [], "n_years": []}
    for m in range(1, 13):
        sel = ms.time.month == m
        y = ms.value[sel]
        ok = np.isfinite(y)
        if ok.sum() < 8:
            for k in ("values", "ci_low", "ci_high", "ci_excludes_zero"):
                out[k].append(None)
            out["n_years"].append(int(ok.sum()))
            continue
        s = sens_slope(years[sel], y, alpha)
        lo, hi = s.ci95[0] * 10, s.ci95[1] * 10
        out["values"].append(s.slope * 10)
        out["ci_low"].append(lo)
        out["ci_high"].append(hi)
        out["ci_excludes_zero"].append(bool(lo > 0 or hi < 0))
        out["n_years"].append(int(ok.sum()))
    return out


def first_last_means(ms, n_years: int = 5) -> dict | None:
    k = 12 * n_years
    if ms.n < 2 * k:
        return None
    a, b = ms.value[:k], ms.value[-k:]
    if np.isfinite(a).sum() < 0.8 * k or np.isfinite(b).sum() < 0.8 * k:
        return None
    return {"first_period": f"{ms.time[0]:%Y-%m} to {ms.time[k - 1]:%Y-%m}", "first_mean": float(np.nanmean(a)),
            "last_period": f"{ms.time[-k]:%Y-%m} to {ms.time[-1]:%Y-%m}", "last_mean": float(np.nanmean(b)),
            "difference": float(np.nanmean(b) - np.nanmean(a))}


# ---------------------------------------------------------------- LLM rewrite (number-checked)
# Only the sections students read most are rewritten, most-read first; the rest keep the template text.
REWRITE_IDS = ["answer", "how_much", "is_it_real", "when", "seasons", "map"]
REWRITE_MAX_TOKENS = 320
REWRITE_INSTRUCTIONS = (
    "Rewrite the REFERENCE text of one report section so a 15-year-old student understands it. Keep every "
    "fact, keep it 3 to 6 short sentences, plain words, no headings, no lists, no markdown. Use ONLY numbers, "
    "years and names that appear in FACTS; copy numbers exactly as written there. Never say what caused a "
    "change: say 'consistent with' or 'associated with'. Do not predict the future. Use the words SIGNIFICANT, "
    "NOT PROVEN, VERIFIED, PROBABLE or NOT VERIFIED only where REFERENCE uses them, exactly as written; never "
    "call something significant or confirmed unless REFERENCE does. Never say the data or the change are not "
    "real: the data are real; only the test can be inconclusive. STUDENT_QUESTION is what the student typed "
    "(often casual); RESEARCH_QUESTION is its precise form. Answer in the student's terms: in 'The short answer', "
    "the first sentence answers STUDENT_QUESTION directly (yes / no / not proven, with the main number).")
# wording the reviewers ruled out; an AI text using it (when REFERENCE does not) keeps the template text
FORBIDDEN = re.compile(r"\b(?:is|isn't|not|be|are|aren't) (?:yet )?real\b|\bno trend exists\b|\bconfirmed\b|"
                       r"\bdefinitely\b|\bcertainly\b|consistent with (?:natural|chance|random)", re.I)
# honesty caveats a rewrite must keep whenever the template states them
MUST_KEEP = [re.compile(x, re.I) for x in (
    r"cannot yet rule out", r"too few years", r"by chance alone", r"significant on its own", r"exploratory",
    r"NOT PROVEN", r"NOT VERIFIED", r"neighbou?r", r"not a forecast", r"simulated from your data")]


def _wording_ok(out: str, reference: str) -> bool:
    ref = {m.group(0).lower() for m in FORBIDDEN.finditer(reference)}
    if not all(m.group(0).lower() in ref for m in FORBIDDEN.finditer(out)):
        return False
    return all(rx.search(out) for rx in MUST_KEEP if rx.search(reference))


def _complete_sentences(out: str) -> str:
    """A reply cut off by the token limit loses its unfinished last sentence (never shown half-written)."""
    if not out or out[-1] in ".!?\"')":
        return out
    cut = max(out.rfind(". "), out.rfind("! "), out.rfind("? "))
    return out[:cut + 1] if cut > 0 else ""


def research_question(report: dict) -> str:
    """The student's casual question restated precisely for the model (variable, place, period, test)."""
    p = report.get("plan") or {}
    return (f"Did {str(p.get('variable_name') or 'the variable').lower()} averaged over {p.get('region_name') or 'the region'} "
            f"change between {p.get('start')} and {p.get('end')}, by how much per decade, when did it change, and "
            f"does the change pass the statistical checks?")


async def rewrite(st, title: str, text: str, facts: dict, question: dict | None = None) -> tuple[str, bool]:
    from ..ai.prompts import SYSTEM_BASE
    from ..ai.verify import verify_text
    f = {**(question or {}), **facts, "section": title, "reference_text": text}
    msgs = [{"role": "system", "content": SYSTEM_BASE + "\n" + REWRITE_INSTRUCTIONS},
            {"role": "user", "content": "FACTS:\n" + json.dumps(f, ensure_ascii=False, default=str)}]
    try:
        out = await st.llm.chat(msgs, max_tokens=REWRITE_MAX_TOKENS)
    except Exception:  # noqa: BLE001 - the template text is always available
        return text, False
    out = _complete_sentences((out or "").strip())
    if not out or "OFF_TOPIC" in out or len(out) < 40:
        return text, False
    if not _wording_ok(out, text) or not verify_text(out, f)["passed"]:
        return text, False
    return out, True


# ---------------------------------------------------------------- report cache (variables, region, period)
CACHE_VERSION = 3
CACHE_TTL_S = 12 * 3600
_MEM: dict[str, tuple[float, dict, dict]] = {}


def cache_key(cands: list[str], region: Region, s0: str, s1: str, alpha: float, creds: dict | None = None) -> str:
    raw = json.dumps([CACHE_VERSION, cands, region.as_dict(), s0, s1, alpha, creds or {}], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _cache_file(st, key: str) -> Path:
    return Path(st.settings.data_dir) / "cache" / "reports" / f"{key}.json"


def cache_get(st, key: str) -> tuple[dict, dict] | None:
    mk = f"{st.settings.data_dir}|{key}"
    hit = _MEM.get(mk)
    if hit is None:
        try:
            d = json.loads(_cache_file(st, key).read_text(encoding="utf-8"))
            hit = (float(d["t"]), d["report"], d["facts"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
    if time.time() - hit[0] > CACHE_TTL_S:
        return None
    _MEM[mk] = hit
    return copy.deepcopy(hit[1]), copy.deepcopy(hit[2])


def cache_put(st, key: str, report: dict, facts: dict) -> None:
    t = time.time()
    facts = json.loads(json.dumps(facts, default=str))
    _MEM[f"{st.settings.data_dir}|{key}"] = (t, copy.deepcopy(report), facts)
    if len(_MEM) > 64:
        _MEM.pop(next(iter(_MEM)))
    try:
        f = _cache_file(st, key)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"t": t, "report": report, "facts": facts}, ensure_ascii=False, default=str),
                       encoding="utf-8")
        tmp.replace(f)
    except OSError:
        pass                                   # the in-memory copy still serves this process


# ---------------------------------------------------------------- the report
async def _plan(st, question: str) -> dict:
    """The offline deterministic planner first: when it already finds a place and a variable, the local-LLM
    planner (about 10 s on a laptop GPU) is skipped. Otherwise the full planner runs."""
    try:
        g = st.ai.guard(question)
        if g.get("on_topic"):
            p = st.ai._deterministic_plan(question)
            if p.get("regions") and p.get("variables"):
                return {**p, "on_topic": True, "guard": g}
    except Exception:  # noqa: BLE001 - fall back to the full planner
        pass
    return await st.ai.plan(question)


async def build_report(st, *, question: str, start: str | None = None, end: str | None = None,
                       variable_id: str | None = None, geometry: dict | None = None, alpha: float = 0.05,
                       progress=None, on_partial=None, refresh: bool = False) -> dict:
    """Deterministic report first (every number computed, template text), published through `on_partial`;
    then the local AI rewrites the most-read sections one by one and published research is added, each step
    published again. Returns the final report (same JSON contract as before, plus per-section status)."""
    async def prog(frac, msg):
        if progress:
            await progress(frac, msg)

    async def publish(rep):
        if on_partial:
            r = on_partial(_clean(rep))
            if asyncio.iscoroutine(r):
                await r

    # ---- 1. plan
    await prog(0.02, "Understanding the question")
    plan = await _plan(st, question)
    if not plan.get("on_topic"):
        raise InvalidRequest(plan.get("message") or "This question is not about Earth data")
    if geometry:
        region = parse_geometry(geometry)
        region_name = geometry.get("name") or region.name or "the chosen area"
    elif plan.get("regions"):
        r0 = plan["regions"][0]
        region = parse_geometry(r0["geometry"])
        region_name = r0.get("name") or region.name or "the region"
    else:
        raise InvalidRequest("Please name a place in the question or draw an area on the map",
                             detail={"needs_user_input": plan.get("needs_user_input")})
    s0, s1, period_source = resolve_period(plan, start, end)
    start_d, end_d = parse_date(s0), parse_date(s1, end=True)
    cands = candidate_variables(st, plan, variable_id)
    if not cands:
        raise InvalidRequest("No dataset in the catalog matches this question; name a quantity such as temperature "
                             "or rainfall")

    shifted = shift_period(st, cands, s0, s1)
    if shifted:
        s0, s1, period_source = shifted
        start_d, end_d = parse_date(s0), parse_date(s1, end=True)

    t0 = time.perf_counter()
    from ..core.auth import credential_status
    key = cache_key(cands, region, s0, s1, alpha, credential_status(st.settings))
    hit = None if refresh else cache_get(st, key)
    if hit:
        report, facts = hit
        report["question"] = question
        report["timing"] = {"cached": True, "deterministic_s": round(time.perf_counter() - t0, 2)}
        await prog(0.5, "Report ready (from cache)")
        await publish(report)
        if report["ai"].get("status") != "done":
            report = await _enrich(st, report, facts, key, prog, publish)
        return _clean(report)

    report, facts = await _deterministic(st, question, plan, region, region_name, s0, s1, period_source, start_d,
                                         end_d, cands, alpha, prog)
    report["timing"] = {"cached": False, "deterministic_s": round(time.perf_counter() - t0, 2)}
    cache_put(st, key, _clean(report), facts)
    await prog(0.5, "Report ready; AI wording on the way")
    await publish(report)
    report = await _enrich(st, report, facts, key, prog, publish)
    report["timing"]["total_s"] = round(time.perf_counter() - t0, 2)
    return _clean(report)


async def _deterministic(st, question, plan, region, region_name, s0, s1, period_source, start_d, end_d, cands,
                         alpha, prog):
    from ..active import engine
    from ..active.runner import _ineligible, _pelt
    from ..active.view import build_view
    from ..api import pipeline
    from ..insights.onset import change_onset
    from ..novelty.court import court as run_court
    from ..novelty.integrity import events_for

    # ---- 2. fetch with fallback (missing credential -> keyless variable of the same criterion)
    attempts, info, vid = [], None, None
    for i, c in enumerate(cands):
        why = _ineligible(st.catalog.variables.get(c), region, start_d, end_d, {})
        if why:
            attempts.append({"variable_id": c, "status": "skipped", "reason": why})
            continue
        await prog(0.05 + 0.02 * i, f"Fetching {st.catalog.variables[c]['name']}")
        try:
            async def sub(frac, msg):
                await prog(0.05 + 0.2 * frac, msg)
            info = await st.ts.build_series(c, region, start_d, end_d, progress=sub)
            vid = c
            attempts.append({"variable_id": c, "status": "used"})
            break
        except Exception as exc:  # noqa: BLE001 - try the next variable
            attempts.append({"variable_id": c, "status": "failed", "reason": getattr(exc, "message", str(exc))[:300]})
    if info is None:
        raise InvalidRequest("None of the matching datasets could be fetched", detail={"attempts": attempts})
    v = st.catalog.get(vid)
    sid = info["series_id"]
    ms = st.store.load(sid)

    # ---- 3. the map cube runs while the series is analysed (its chunks are usually in the HTTP cache by now)
    map_task = asyncio.create_task(_trend_map(st, vid, v, region, start_d, end_d, alpha))

    # ---- 4. analysis, active-trend checks, BEAST, PELT: independent stages run concurrently
    await prog(0.3, "Running trend tests, checks and change dating")

    async def novelty(kind, fn, params):
        return await pipeline.cached_novelty(st, kind, sid, fn, {"alpha": alpha, **params})

    try:
        an, det, court_full, onset = await asyncio.gather(
            pipeline.cached_analysis(st, sid, alpha=alpha),
            novelty("active_detect", lambda m: engine.detect(m, alpha), {}),
            novelty("report_court_v2", lambda m: _court_summary(run_court(m, alpha)), {}),
            pipeline.cached_novelty(
                st, "onset", sid, lambda m: change_onset(m, seams=events_for(m), pelt_breaks=_pelt(m), alpha=alpha,
                                                         n_surrogates=49), {"alpha": alpha, "k": 49, "pelt": True}))
        checks, beast, label = [], None, None
        if det["state"] != "too_short":
            W = {"w": det["window_years"]}
            checks = list(await asyncio.gather(
                novelty("active_integrity", lambda m: engine.check_integrity(m, det), W),
                novelty("active_court", lambda m: engine.check_court(m, det, alpha), W),
                novelty("active_chance", lambda m: engine.check_chance(m, det, alpha), W),
                novelty("active_stability", lambda m: engine.check_stability(m, det, alpha), W)))
            beast = engine.beast_gate(onset, det)
            if det["active"]:
                label = engine.label(det, checks, beast)
        view, seasons = await asyncio.gather(
            build_view(st, sid, alpha=alpha, detect=det if det["state"] != "too_short" else None, verdict=label,
                       explain=False),
            run_in_threadpool(seasonal_slopes, ms, alpha))
    except BaseException:
        map_task.cancel()
        raise
    onset, view = _soften_late_breaks(onset, view, ms)
    await prog(0.45, "Building the trend map")
    trend_map, map_note = await map_task

    # ---- 5. sections (deterministic text + facts); research and AI wording come afterwards
    direction = _verdict(an).get("direction")
    research_on = bool(st.settings.research_enabled and direction in ("rising", "falling"))
    ctx = dict(st=st, v=v, vid=vid, region_name=region_name, an=an, ms=ms, det=det, checks=checks, beast=beast,
               label=label, court=court_full, onset=onset, view=view, seasons=seasons, trend_map=trend_map,
               map_note=map_note, research=None, research_pending=research_on, attempts=attempts, info=info,
               period_source=period_source, region=region, alpha=alpha)
    sections = _sections(ctx)
    facts = {s["id"]: s.pop("_facts") for s in sections}
    llm_on = bool((await st.llm.status()).get("available")) if st.llm.enabled else False
    for s in sections:
        s["text_source"] = "template"
        s["ai_status"] = "pending" if (llm_on and s["id"] in REWRITE_IDS) else "not_rewritten"
    prov = an.get("provenance") or {}
    report = {
        "question": question,
        "plan": {"variable_id": vid, "variable_name": v["name"], "units": an.get("units"), "region_name": region_name,
                 "geometry": region.as_dict(), "start": s0, "end": s1, "source": v.get("source"),
                 "period_source": period_source, "attempts": attempts, "planner": plan.get("planner")},
        "headline": _headline(ctx),
        "sections": sections,
        "glossary": GLOSSARY,
        "provenance": {**prov, "series_id": sid, "map": (trend_map or {}).get("provenance")},
        "limits": _limits(ctx),
        "ai": {"used": False, "label": "template", "sections_rewritten": 0, "sections_total": len(sections),
               "status": "writing" if (llm_on or research_on) else "done",
               "pending": [s["id"] for s in sections if s["ai_status"] == "pending"],
               "research": "pending" if research_on else "off"},
    }
    if research_on:
        facts["_research_args"] = {"variable_id": vid, "variable_name": v.get("name"), "region_name": region_name,
                                   "direction": direction}
    return report, facts


async def _enrich(st, report: dict, facts: dict, key: str, prog, publish) -> dict:
    """AI wording section by section (most-read first), then published research; each step is published."""
    secs = {s["id"]: s for s in report["sections"]}
    todo = [i for i in REWRITE_IDS if secs.get(i, {}).get("ai_status") == "pending"]
    if todo and not (st.llm.enabled and (await st.llm.status()).get("available")):
        for i in todo:
            secs[i]["ai_status"] = "unavailable"
        todo = []
    for n, i in enumerate(todo):
        s = secs[i]
        await prog(0.5 + 0.4 * n / max(len(todo), 1), f"AI wording: {s['title']}")
        new, ok = await rewrite(st, s["title"], s["text"], facts.get(i) or {},
                                {"STUDENT_QUESTION": report.get("question"), "RESEARCH_QUESTION": research_question(report)})
        if ok:
            s["text"], s["text_source"], s["ai_status"] = new, "local_llm", "rewritten"
        else:
            s["ai_status"] = "kept_template"
        _ai_summary(report)
        await publish(report)

    ra = facts.get("_research_args")
    if report["ai"].get("research") == "pending" and ra:
        await prog(0.92, "Looking for published research")
        research = None
        try:
            from ..research.evidence import research_evidence
            s = st.settings
            research = await asyncio.wait_for(research_evidence(
                st.http, st.llm, variable_id=ra["variable_id"], variable_name=ra["variable_name"],
                region_name=ra["region_name"], direction=ra["direction"], max_age_years=s.research_max_age_years,
                per_source=s.research_per_source, springer_key=s.springer_api_key,
                semantic_key=s.semantic_scholar_api_key, ads_token=s.ads_api_token), 60)
        except Exception:  # noqa: BLE001 - literature is optional context
            research = None
        ctx_sec = secs.get("context")
        if ctx_sec is not None:
            ctx_sec["text"], ctx_sec["data"] = _context_text(facts.get("context") or {}, research, ra["direction"],
                                                             pending=False)
        report["ai"]["research"] = "done" if research else "unavailable"
    _ai_summary(report)
    report["ai"]["status"] = "done"
    cache_put(st, key, _clean(report), facts)
    await publish(report)
    return report


def _ai_summary(report: dict) -> None:
    used = sum(s.get("text_source") == "local_llm" for s in report["sections"])
    report["ai"].update(used=used > 0, label=AI_LABEL if used else "template", sections_rewritten=used,
                        pending=[s["id"] for s in report["sections"] if s.get("ai_status") == "pending"])


async def _trend_map(st, vid, v, region, start_d, end_d, alpha):
    from ..insights.cube import cube_trends
    mvid = map_variable(st, vid)
    box, from_point = map_box(region)
    if mvid is None:
        return None, f"No keyless gridded dataset is available for {v['name']}, so no map could be drawn."
    try:
        mv = st.catalog.get(mvid)
        times, cube, lat, lon, units, mprov = await st.ts.connectors["erddap"].fetch_cube(
            FetchRequest(mv, box, max(start_d, parse_date(mv["coverage_start"])) if mv.get("coverage_start")
                         else start_d, end_d))
        conv = mv.get("convert") or {}
        cube = cube * float(conv.get("factor", 1.0)) + float(conv.get("offset", 0.0))
        units = conv.get("units") or units
        masked = 0
        if region.polygon and not from_point:      # keep only cells whose centre is inside the drawn polygon
            from ..core.geometry import point_in_polygon
            lon_a = np.asarray(lon, float)
            lon_w = np.where(lon_a > 180, lon_a - 360, lon_a)
            inside = np.array([[point_in_polygon(x, y, region.polygon) for x in lon_w] for y in np.asarray(lat)])
            if inside.any() and not inside.all():
                cube = np.where(inside[None, :, :], cube, np.nan)
                masked = int((~inside).sum())
        months = pd.DatetimeIndex(times).month.to_numpy()
        ct = await run_in_threadpool(cube_trends, cube, months, lat, lon, alpha=alpha)
        n_cells = sum(x is not None for row in ct["slope_per_decade"] for x in row)
        return {
            "variable_id": mvid, "variable_name": mv["name"], "lat": ct["lat"], "lon": ct["lon"],
            "slope_per_decade": ct["slope_per_decade"], "significant": ct["significant"], "units": units,
            "area_fraction_rising": ct["area_fraction_rising"], "area_fraction_falling": ct["area_fraction_falling"],
            "area_mean_slope_per_decade": ct["area_mean_slope_per_decade"], "n_cells": n_cells,
            "field_significance": {"method": ct["method"], "alpha_fdr": 2 * alpha,
                                   "any_significant": any(any(r) for r in ct["significant"]),
                                   "plain_language": ct["plain_language"]},
            "bbox": list(box.bbox), "box_around_point": from_point, "masked_to_region": masked > 0,
            "cells_masked_outside_region": masked, "spatial_resolution": _res_text(mv),
            "period": [str(pd.Timestamp(times[0]).date()), str(pd.Timestamp(times[-1]).date())],
            "provenance": mprov.to_dict(), "label": "exploratory",
        }, None
    except Exception as exc:  # noqa: BLE001 - the map is one section; the report goes on
        return None, f"The trend map could not be built: {getattr(exc, 'message', str(exc))[:200]}"


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))


LATE_BREAK_MONTHS = 36


def _soften_late_breaks(onset: dict, view: dict, ms) -> tuple[dict, dict]:
    """A BEAST change within ~3 years of the record end that PELT does not find and whose dating interval or
    after-change slope is very uncertain is reported as 'possible', never 'confirmed': too few years follow it."""
    events = onset.get("events") or []
    if not events:
        return onset, view
    end = f"{ms.time[-1]:%Y-%m}"
    segs = onset.get("segments") or []
    last_ci = (segs[-1].get("ci95_adj_per_decade") if segs else None) or [None, None]
    last_unsure = last_ci[0] is not None and last_ci[1] is not None and last_ci[0] < 0 < last_ci[1]
    soft, new_events = set(), []
    for e in events:
        e = dict(e)
        iv = e.get("interval90") or [None, None]
        wide = bool(iv[0] and iv[1] and _months_between(iv[0], iv[1]) >= 12)
        after = _months_between(e["date"], end) if e.get("date") else 999
        if (e.get("status") == "confirmed" and after <= LATE_BREAK_MONTHS and not e.get("agrees_with_pelt")
                and (wide or last_unsure)):
            e["status"] = "possible"
            e["late_in_record"] = True
            e["status_note"] = ("Close to the end of the record, not found by PELT and very uncertain, so it is "
                                "reported as possible, not confirmed.")
            soft.add(e["date"])
        new_events.append(e)
    if not soft:
        return onset, view
    markers = [({**m, "kind": "beast_possible"} if m.get("kind") == "beast_confirmed" and m.get("date") in soft else m)
               for m in view.get("markers") or []]
    return {**onset, "events": new_events}, {**view, "markers": markers}


def _court_summary(c: dict) -> dict:
    return {"stamp": c["stamp"], "chosen_test": c["chosen_test"], "reason": c.get("reason"),
            "jurors_significant": c["jurors_significant"], "n_jurors": len(c["jurors"]), "flips": c.get("flips"),
            "plain_language": c.get("plain_language"),
            "jurors": [{"id": j["id"], "name": j.get("name"), "p": j.get("p"), "significant": j.get("significant"),
                        "slope_per_decade": j.get("slope_per_decade")} for j in c["jurors"]]}


def _verdict(an: dict) -> dict:
    return an.get("verdict") or {}


def _not_sig_sentence(direction: str | None) -> str:
    what = {"rising": "rise", "falling": "fall"}.get(direction, "change")
    return f"The tests cannot yet rule out that natural year-to-year swings produced this {what}."


def _headline(c: dict) -> str:
    an, v = c["an"], c["v"]
    vd = _verdict(an)
    per = an.get("period") or {}
    u = an.get("units") or ""
    dirw = {"rising": "rose", "falling": "fell"}.get(vd.get("direction"), "changed")
    sig = ("This trend is statistically significant." if vd.get("significant")
           else _not_sig_sentence(vd.get("direction")))
    if vd.get("direction") not in ("rising", "falling"):
        return (f"In {c['region_name']}, {short_name(v)} showed no clear trend from "
                f"{per.get('start')} to {per.get('end')} ({fmt(vd.get('rate_per_decade'))} {u} per decade). {sig}")
    return (f"In {c['region_name']}, {short_name(v)} {dirw} by about "
            f"{fmt(abs(vd['rate_per_decade'])).lstrip('+')} {u} per decade from {per.get('start')} to {per.get('end')}, "
            f"a total change of about {fmt(vd.get('total_change'))} {u}. {sig}")


def _sec(id_, title, kind, text, data, facts) -> dict:
    return {"id": id_, "title": title, "kind": kind, "text": text, "data": data, "_facts": facts}


PROVIDER = {"erddap": "NOAA", "giovanni": "NASA", "appeears": "NASA", "ncei": "NOAA", "opendap": "NASA",
            "nsidc": "NSIDC", "usgs": "USGS", "coops": "NOAA"}
NEIGHBOURS = {
    "india": "the Tibetan Plateau, parts of Pakistan, Nepal, Bangladesh and Myanmar, and parts of the Arabian Sea "
             "and the Bay of Bengal",
}
SEN_EXPLAIN = "the median of the slopes between every pair of months, so a few extreme months cannot pull it much"
BEAST_EXPLAIN = "a Bayesian method that estimates when the trend changed and how likely each change is"
PELT_EXPLAIN = "a fast method that finds the best places to split the record into straight pieces"
FIELD_EXPLAIN = ("a correction that removes cells that look significant only by luck when hundreds of cells are "
                 "tested at once")
JUROR_PLAIN = {"ols_naive": "simple regression test (ignores month-to-month persistence)",
               "ols_ar1": "regression test corrected for month-to-month persistence",
               "mk_ess_ar1": "Mann-Kendall test corrected for month-to-month persistence",
               "seasonal_mk": "Seasonal Mann-Kendall test", "sen_ci": "Sen's slope range"}
CHECK_NAME = {"integrity": "Data quality", "court": "Trend Court", "chance": "Could it be chance?",
              "stability": "Same answer with nearby years?", "ai_review": "AI reviewer (advisory)"}


def _court_explain(court: dict, direction: str | None) -> str:
    """Why the stamp is what it is, in plain words, from the jurors returned by Trend Court."""
    lean = {"rising": "a rise", "falling": "a fall"}.get(direction, "a trend")
    n_sig, n = court.get("jurors_significant") or 0, court.get("n_jurors") or 0
    by = {j["id"]: j for j in court.get("jurors") or []}
    if court.get("stamp") == "SIGNIFICANT":
        return (f"Trend Court gives the stamp SIGNIFICANT: {n_sig} of {n} tests find {lean}, including the tests "
                f"corrected for month-to-month persistence.")
    weak = [by[i] for i in ("ols_ar1", "mk_ess_ar1") if i in by and not by[i].get("significant")]
    if weak:
        names = " and the ".join(JUROR_PLAIN.get(j["id"]) or (j.get("name") or j["id"].replace("_", " "))
                                 + (f" (p = {num(j['p'], 3)})" if j.get("p") is not None else "") for j in weak)
        why = f"the stricter test that matters most for data like these, the {names}, is not convincing enough"
    else:
        why = "the tests chosen for this data do not agree strongly enough"
    head = (f"most tests ({n_sig} of {n}) lean towards {lean}" if n_sig * 2 > n
            else f"only {n_sig} of {n} tests find {lean}")
    return (f"Trend Court gives the stamp NOT PROVEN: {head}, but {why}. Here one warm or cool month tends to be "
            f"followed by a similar one (month-to-month persistence), which makes simple tests look more certain "
            f"than they are.")


def _detect_text(det: dict, an: dict) -> str:
    """The recent-window detector's result, worded so it does not contradict the full-record tests."""
    st_ = det.get("state")
    if st_ == "too_short":
        return det.get("plain_language") or ""
    rw = det.get("recent_window") or {}
    win = f"{str(rw.get('start', ''))[:4]}–{str(rw.get('end', ''))[:4]}"
    full = ("Full record: the tests agree on a significant trend." if _verdict(an).get("significant") else
            "Full record: the tests disagree (see Trend Court).")
    if st_ in ("none", "stalled"):
        return (f"{full} Last {det.get('window_years')} years ({win}): too short and noisy to detect a trend on its "
                f"own.")
    return f"{full} Last {det.get('window_years')} years ({win}): {det.get('plain_language')}"


def _check_line(ch: dict, det: dict) -> tuple[str, str, str]:
    rw = det.get("recent_window") or {}
    w = det.get("window_years")
    win = f"{rw.get('start')} to {rw.get('end')}"
    where = {"integrity": "whole record", "court": f"last {w} years, {win}", "chance": f"last {w} years, {win}",
             "stability": f"windows close to the last {w} years"}.get(ch["check"], "")
    txt = re.sub(r"^Trend Court(?: on the recent window)?: ", "", ch["plain_language"])
    return CHECK_NAME.get(ch["check"], ch["check"].replace("_", " ")), where, txt


def _limits_clean(caveats: list[str]) -> list[str]:
    return [re.sub(r"\(lag-1 r = ([-0-9.]+)\)",
                   r"(lag-1 autocorrelation r = \1: one warm or cool month tends to be followed by a similar one)", c)
            for c in caveats]


def _context_text(cfacts: dict, research: dict | None, direction: str | None, pending: bool) -> tuple[str, dict]:
    t = ["The data show what happened, not why it happened.",
         cfacts.get("family_context") or "Possible explanations need separate evidence; this tool does not test "
                                         "them here.",
         "To test an explanation, compare this record with a possible driver (for example rainfall or ocean "
         "temperature) using the drivers tool; a match there is still only an association."]
    data: dict = {"research": None}
    if pending:
        data["research_status"] = "pending"
    elif research:
        data["research"] = research
        data["research_status"] = "done"
        t.append("Published research: " + _research_sentence(research, direction, cfacts.get("variable") or
                                                             "this quantity", cfacts.get("region")))
    else:
        data["research_status"] = "unavailable"
    return " ".join(x for x in t if x), data


def _cite(p: dict) -> str | None:
    authors = [str(a).strip() for a in (p.get("authors") or []) if a and str(a).strip() not in ("?", "Unknown")]
    if not authors or not p.get("year"):
        return None
    last = authors[0].split()[-1]
    last = last.title() if last.isupper() else last
    return f"{last} et al. {p['year']}" if len(authors) > 1 else f"{last} {p['year']}"


def _research_sentence(rs: dict, direction: str | None, var: str, region: str | None) -> str:
    """Counts come from the research module (stances read from abstracts, compared with the full-record
    direction); only papers with named authors are cited."""
    if not any((s or {}).get("status") == "ok" for s in rs.get("sources") or []):
        return "the literature sources could not be reached, so no research comparison was made."
    ag = rs.get("agreement") or {}
    since = rs.get("since_year")
    where = f" in {region}" if region else ""
    papers = rs.get("papers") or []
    word = {"rising": "a rise", "falling": "a fall"}.get(direction, "a change")
    sup = [c for c in (_cite(p) for p in papers if p.get("stance") == direction) if c][:3]
    con = [c for c in (_cite(p) for p in papers if p.get("stance") in ("rising", "falling")
                       and p.get("stance") != direction) if c][:2]
    n_sup, n_con = ag.get("n_supporting", 0) or 0, ag.get("n_conflicting", 0) or 0
    lab = ag.get("label")
    if lab == "no_literature":
        return f"no recent ({since}+) studies on {var}{where} were found in the searched literature sources."
    if not (n_sup or n_con):
        return f"studies on {var}{where} were found, but their abstracts do not state a clear direction."
    eg_s = f" (for example {'; '.join(sup)})" if sup else ""
    eg_c = f" (for example {'; '.join(con)})" if con else ""
    tail = " Studies use other datasets, periods and areas, so this is context, not a check of these numbers."
    if lab == "supported":
        return (f"of the recent studies ({since}+) whose abstracts state a direction, {n_sup} also report {word} "
                f"of {var}{where}{eg_s}" + (f" and {n_con} report the opposite{eg_c}" if n_con else "") + "." + tail)
    if lab == "conflicts":
        return (f"caution: {n_con} recent studies report the opposite direction for {var}{where}{eg_c}, and {n_sup} "
                f"agree{eg_s}." + tail)
    return f"research is mixed: {n_sup} studies report {word}{eg_s} and {n_con} the opposite{eg_c}." + tail


def _annual_swing(an: dict) -> float | None:
    """Standard deviation of the yearly means of the deseasonalized series (years with >= 10 valid months)."""
    ch = an.get("chart") or {}
    tt, des = ch.get("time") or [], ch.get("deseasonalized") or []
    if not tt or len(tt) != len(des):
        return None
    years: dict[str, list[float]] = {}
    for t, x in zip(tt, des):
        if x is not None and math.isfinite(x):
            years.setdefault(str(t)[:4], []).append(float(x))
    means = [float(np.mean(v)) for v in years.values() if len(v) >= 10]
    return float(np.std(means, ddof=1)) if len(means) >= 5 else None


def _res_text(v: dict) -> str:
    ds = v.get("dataset") or {}
    return v.get("spatial_resolution") or ("about 1.9° (roughly 200 km) grid" if v.get("source") == "erddap"
                                           and "ncep" in ((ds.get("short_name") or "") + v.get("name", "")).lower()
                                           else "see dataset documentation")


def _sections(c: dict) -> list[dict]:
    an, v, ms, det = c["an"], c["v"], c["ms"], c["det"]
    vd = _verdict(an)
    per = an.get("period") or {}
    u = an.get("units") or ""
    ols, sen = an.get("ols") or {}, an.get("sen") or {}
    name = short_name(v)
    direction = vd.get("direction")
    alpha = c["alpha"]
    base_facts = {"variable": name, "region": c["region_name"], "units": u, "start": per.get("start"),
                  "end": per.get("end"), "years": per.get("years")}
    trend_facts = {**base_facts, "direction": direction, "significant": vd.get("significant"),
                   "rate_per_decade": vd.get("rate_per_decade"), "total_change": vd.get("total_change")}
    provider = PROVIDER.get(v.get("source"), v.get("source") or "the data provider")
    out = []

    # 1 answer: one headline rate (Sen's slope) with its own range; the regression separately with its own
    ci = ols.get("ci95_adj_per_decade") or [None, None]
    sci = sen.get("ci95_per_decade") or [None, None]
    p_ols, p_mk = ols.get("p_adj"), (an.get("mann_kendall") or {}).get("p")
    what = {"rising": "rise", "falling": "fall"}.get(direction, "change")
    if vd.get("significant"):
        sig_t = ("Both the regression test and the Mann-Kendall test, each corrected for month-to-month "
                 "persistence, find this trend statistically significant.")
    else:
        if p_mk is not None and p_mk < alpha:
            first = (f"The Mann-Kendall test finds the {what} significant (p = {num(p_mk, 3)}), but the regression "
                     f"corrected for month-to-month persistence does not (p = {num(p_ols, 3)}).")
        elif p_ols is not None and p_ols < alpha:
            first = (f"The regression finds the {what} significant (p = {num(p_ols, 3)}), but the Mann-Kendall test "
                     f"does not (p = {num(p_mk, 3)}).")
        else:
            first = (f"Neither the regression (p = {num(p_ols, 3)}) nor the Mann-Kendall test (p = {num(p_mk, 3)}) "
                     f"is below {alpha}.")
        sig_t = (f"{first} {_not_sig_sentence(direction)} The monthly values themselves are real data from "
                 f"{provider}; it is the trend test that is inconclusive.")
    shift_note = c["period_source"][len("shifted: "):] + "." if c["period_source"].startswith("shifted: ") else ""
    t = [shift_note, f"We measured {name.lower()} averaged over {c['region_name']}, one value per month, from {per.get('start')} "
         f"to {per.get('end')} ({num(per.get('years'), 1)} years).",
         f"Best estimate of the trend (Sen's slope: {SEN_EXPLAIN}): {fmt(sen.get('slope_per_decade'))} {u} per "
         f"decade, with a 95% range of {fmt(sci[0])} to {fmt(sci[1])} {u} per decade.",
         f"That adds up to about {fmt(vd.get('total_change'))} {u} over the whole period.",
         f"A straight regression line, corrected for month-to-month persistence, gives a separate estimate of "
         f"{fmt(ols.get('slope_per_decade'))} {u} per decade (its own 95% range {fmt(ci[0])} to {fmt(ci[1])}).",
         sig_t,
         "The sections below show the data, how big the change is, whether it survives extra checks, when it "
         "changed, which months changed most and where inside the region it changed."]
    out.append(_sec("answer", "The short answer", "text", " ".join(x for x in t if x), {},
                    {**trend_facts, "sen_per_decade": sen.get("slope_per_decade"), "sen_ci95": sci,
                     "ols_per_decade": ols.get("slope_per_decade"), "ols_ci95": ci, "p_regression": p_ols,
                     "p_mann_kendall": p_mk, "alpha": alpha, "provider": provider}))

    # 2 data
    prov = an.get("provenance") or {}
    ds = v.get("dataset") or {}
    agency = {"erddap": "NOAA (served by NOAA ERDDAP)", "giovanni": "NASA GES DISC (Giovanni)",
              "appeears": "NASA LP DAAC (AppEEARS)", "ncei": "NOAA NCEI", "opendap": "NASA Earthdata (Cloud OPeNDAP)",
              "nsidc": "NSIDC", "usgs": "USGS NWIS", "coops": "NOAA CO-OPS"}.get(v.get("source"), v.get("source"))
    rows = [["Dataset", ds.get("short_name") or prov.get("dataset_short_name") or v["name"]],
            ["Source / agency", agency],
            ["Version", ds.get("version") or prov.get("version") or "n/a"],
            ["DOI", ds.get("doi") or prov.get("doi") or "n/a"],
            ["Spatial resolution", _res_text(v)],
            ["Time step", v.get("native_resolution", "monthly")],
            ["Period", f"{per.get('start')} to {per.get('end')}"],
            ["Valid months", f"{per.get('n_valid')} of {per.get('n_months')}"],
            ["What one number means", f"The average {name.lower()} over {c['region_name']} for one month, in {u}"
                                       + (" (area mean with cos(latitude) weights)" if not c["region"].is_point else "")],
            ["Period chosen", c["period_source"]],
            # the challenge's own time-series resources: deseasonalised monthly series + slope significance test
            ["Method follows", "Time-series analysis of remotely-sensed SeaWiFS chlorophyll (NASA NTRS 20090042747, "
                               "https://ntrs.nasa.gov/citations/20090042747): monthly series, seasonal cycle removed, "
                               "trend slope tested for significance; plus Mann-Kendall / Sen's slope"]]
    used_fallback = [a for a in c["attempts"] if a["status"] == "failed"]
    t = [f"The numbers come from {ds.get('short_name') or v['name']}, provided by {agency}.",
         v.get("short_definition") or "",
         f"The record has {per.get('n_valid')} valid months out of {per.get('n_months')} between {per.get('start')} "
         f"and {per.get('end')}; missing months are left as gaps and never filled in.",
         f"Each value is the average over {c['region_name']} for one month, in {u}."]
    if used_fallback:
        t.append(f"The first choice of dataset ({used_fallback[0]['variable_id']}) could not be fetched, so this "
                 f"freely available dataset was used instead.")
    out.append(_sec("data", "Where the numbers come from", "table", " ".join(x for x in t if x),
                    {"columns": ["Item", "Value"], "rows": rows},
                    {**base_facts, "n_valid": per.get("n_valid"), "n_months": per.get("n_months"),
                     "dataset": ds.get("short_name"), "definition": v.get("short_definition")}))

    # 3 series chart
    t = [f"The chart shows every monthly value of {name.lower()} in {c['region_name']} (thin line).",
         "The big regular waves are the seasons; the second line removes that seasonal cycle so the slow change "
         "is easier to see.",
         f"The straight line is the Sen's slope trend of {fmt(sen.get('slope_per_decade'))} {u} per decade.",
         f"The shaded curve comes from BEAST ({BEAST_EXPLAIN}); the probability line shows how likely a change in "
         f"trend is at each month.",
         f"Markers show dates where BEAST or PELT ({PELT_EXPLAIN}) find a change in the trend."]
    if c["view"].get("recent_window"):
        rw = c["view"]["recent_window"]
        t.append(f"The highlighted recent window ({rw['start']} to {rw['end']}) is the part tested for an active trend.")
    out.append(_sec("series", "The whole record, month by month", "chart", " ".join(t), c["view"],
                    {**base_facts, "sen_slope_per_decade": sen.get("slope_per_decade"),
                     "recent_window": c["view"].get("recent_window")}))

    # 4 how much (+ "is that a lot?")
    des = np.asarray([np.nan if x is None else x for x in (an.get("chart") or {}).get("deseasonalized") or []], float)
    sd = float(np.nanstd(des, ddof=1)) if np.isfinite(des).sum() > 2 else None
    tot = vd.get("total_change")
    in_sd = (tot / sd) if (tot is not None and sd) else None
    swing = _annual_swing(an)
    in_swing = (abs(tot) / swing) if (tot is not None and swing) else None
    fl = first_last_means(ms)
    rows = [["Trend rate (Sen's slope)", f"{fmt(sen.get('slope_per_decade'))} {u}/decade",
             f"95% CI {fmt(sci[0])} to {fmt(sci[1])}"],
            ["Trend rate (regression, corrected for persistence)", f"{fmt(ols.get('slope_per_decade'))} {u}/decade",
             f"95% CI {fmt(ci[0])} to {fmt(ci[1])}"],
            ["Total change over the period", f"{fmt(tot)} {u}", f"over {num(per.get('years'), 1)} years"],
            ["Typical year-to-year swing of the yearly average (1 standard deviation)", f"{num(swing)} {u}",
             "after removing the seasons"],
            ["Size of normal month-to-month ups and downs (1 standard deviation)", f"{num(sd)} {u}",
             "after removing the seasons"],
            ["Total change in month-to-month standard deviations", f"{fmt(in_sd)}",
             "above 1 means bigger than the usual noise"]]
    if fl:
        rows += [[f"Mean of first 5 years ({fl['first_period']})", f"{num(fl['first_mean'])} {u}", ""],
                 [f"Mean of last 5 years ({fl['last_period']})", f"{num(fl['last_mean'])} {u}", ""],
                 ["Last 5 years minus first 5 years", f"{fmt(fl['difference'])} {u}", "simple difference of means"]]
    t = [f"The trend rate is {fmt(sen.get('slope_per_decade'))} {u} per decade by Sen's slope and "
         f"{fmt(ols.get('slope_per_decade'))} {u} per decade by a regression line.",
         f"Over the {num(per.get('years'), 1)} years that adds up to a total change of about {fmt(tot)} {u}."]
    if in_swing is not None:
        t.append(f"Is that a lot? The yearly average typically differs by about {num(swing)} {u} from one year to "
                 f"another just through natural swings, so the total change is about {num(in_swing, 1)} times that "
                 f"swing" + ("; that is small against the natural ups and downs, which is why the tests struggle to "
                             "be sure." if in_swing < 1.5 else "; clearly bigger than the natural ups and downs."))
    if in_sd is not None:
        t.append(f"Single months swing even more (about {num(sd)} {u}), so the total change is {num(abs(in_sd))} "
                 f"times the month-to-month noise.")
    if fl:
        t.append(f"A simple check without any model: the average of the first five years ({fl['first_period']}) was "
                 f"{num(fl['first_mean'])} {u} and the average of the last five years ({fl['last_period']}) was "
                 f"{num(fl['last_mean'])} {u}, a difference of {fmt(fl['difference'])} {u}.")
    out.append(_sec("how_much", "How big is the change?", "table", " ".join(x for x in t if x),
                    {"columns": ["Measure", "Value", "Note"], "rows": rows, "units": u,
                     "rate_per_decade": ols.get("slope_per_decade"), "ci95_per_decade": ci,
                     "sen_per_decade": sen.get("slope_per_decade"), "sen_ci95_per_decade": sci, "total_change": tot,
                     "sd": sd, "change_in_sd": in_sd, "annual_swing_sd": swing, "change_in_annual_swings": in_swing,
                     "first_last_5y": fl},
                    {**trend_facts, "ols_per_decade": ols.get("slope_per_decade"), "ci95": ci,
                     "sen_per_decade": sen.get("slope_per_decade"), "sen_ci95": sci, "sd": sd, "change_in_sd": in_sd,
                     "annual_swing": swing, "change_in_annual_swings": in_swing, "first_last": fl}))

    # 5 is it real
    court = dict(c["court"])
    lab = c["label"]
    court_txt = _court_explain(court, direction)
    court["plain_language"] = court_txt
    court["chosen_test_name"] = JUROR_PLAIN.get(court.get("chosen_test")) or next(
        (j.get("name") for j in court.get("jurors") or [] if j.get("id") == court.get("chosen_test")), None)
    detect_txt = _detect_text(det, an)
    if det["state"] == "too_short":
        vtxt, verdict_label = det["plain_language"], "NOT VERIFIED"
    elif lab:
        vtxt, verdict_label = lab["plain_language"], lab["label"]
    else:
        vtxt, verdict_label = ("NOT VERIFIED: the active-trend checks only certify a trend that is clear in the most "
                               "recent years, and it is not clear there."), "NOT VERIFIED"
    t = [court_txt, f"Active-trend verdict: {vtxt}", detect_txt]
    check_rows = []
    for ch in c["checks"]:
        nm, where, txt = _check_line(ch, det)
        t.append(f"{nm} ({where}; {ch['status']}): {txt}")
        check_rows.append({"check": nm, "id": ch["check"], "window": where, "status": ch["status"], "text": txt})
    if c["beast"]:
        t.append(f"BEAST ({BEAST_EXPLAIN}), last year of the record: {c['beast']['plain_language']}")
    limit = engine_limit() if verdict_label == "VERIFIED" else None
    if limit:
        t.append(limit)
    out.append(_sec("is_it_real", "Is the trend real? Independent checks", "checks", " ".join(t),
                    {"verdict": verdict_label, "why": (lab or {}).get("why"), "state": det.get("state"),
                     "detect_plain_language": detect_txt, "checks": check_rows,
                     "beast": c["beast"], "court": court, "limit": limit},
                    {**base_facts, "direction": direction, "significant": vd.get("significant"),
                     "court": {k: court.get(k) for k in ("stamp", "jurors_significant", "n_jurors")},
                     "court_text": court_txt, "detect": detect_txt, "checks": [r["text"] for r in check_rows],
                     "windows": [r["window"] for r in check_rows], "beast": (c["beast"] or {}).get("plain_language"),
                     "verdict": vtxt}))

    # 6 when
    onset = c["onset"]
    events = onset.get("events") or []
    pelt = [m for m in c["view"].get("markers", []) if m["kind"] == "pelt_break"]
    segs = onset.get("segments") or []
    t = [f"BEAST ({BEAST_EXPLAIN}) and PELT ({PELT_EXPLAIN}) look for dates where the trend changed."]
    if onset.get("status") != "ok":
        t.append(onset.get("plain_language") or "BEAST could not date changes for this record.")
    elif events:
        t.append(f"BEAST finds {len(events)} candidate change(s) in the trend.")
        for e in events:
            iv = e.get("interval90") or [None, None]
            if e.get("late_in_record"):
                t.append(f"Around {e['date']}: a possible short jump near the end of the record (probability "
                         f"{num(e.get('probability'))}, approximate interval {iv[0]} to {iv[1]}); PELT does not find "
                         f"it and too few years follow it to judge it.")
                continue
            t.append(f"Around {e['date']} ({e['status']}, probability {num(e.get('probability'))}, approximate "
                     f"interval {iv[0]} to {iv[1]})"
                     + ("; PELT finds a break within two years of it too" if e.get("agrees_with_pelt") else "")
                     + (", next to a possible instrument effect" if (e.get("near_seam") or {}).get("label") else "")
                     + ".")
        if segs:
            t.append("Trend in each piece: " + "; ".join(
                f"{sg.get('start')} to {sg.get('end')}: {fmt(sg.get('slope_per_decade'))} {u} per decade"
                + (" (significant)" if sg.get("significant") else " (not significant)") for sg in segs) + ".")
            whole = sen.get("slope_per_decade")
            sl = [sg.get("slope_per_decade") for sg in segs]
            if (len(segs) >= 2 and whole and all(x is not None for x in sl)
                    and all(abs(x) > abs(whole) and np.sign(x) == np.sign(whole) for x in sl)):
                t.append(f"Every piece is steeper than the whole record ({fmt(whole)} {u} per decade), so the pieces "
                         f"are joined by a step in level: this looks like a jump between periods, not a steady "
                         f"speeding-up.")
    else:
        t.append("BEAST finds no clear change in the trend: the record is best described by one steady trend.")
    t.append(("PELT splits the record at " + ", ".join(p["date"] for p in pelt) + ".") if pelt else
             "PELT finds no break in the trend.")
    t.append("A change date only says when the rate of change shifted; it does not say why.")
    out.append(_sec("when", "When did it change?", "chart", " ".join(t),
                    {**c["view"], "events": events, "pelt_breaks": [p["date"] for p in pelt],
                     "segments": segs, "onset_plain_language": onset.get("plain_language")},
                    {**base_facts, "direction": direction, "events": events, "pelt": [p["date"] for p in pelt],
                     "segments": segs, "whole_record_sen_per_decade": sen.get("slope_per_decade"),
                     "onset": onset.get("plain_language")}))

    # 7 seasons: 12 tests at once, so say how many would pass by chance
    se = c["seasons"]
    vals = [(MONTHS[i], x, se["ci_excludes_zero"][i]) for i, x in enumerate(se["values"]) if x is not None]
    n_tests = len(vals)
    expect = n_tests * alpha
    note = (f"{n_tests} months were tested, so about {num(expect, 1)} of them would show a 95% range that excludes "
            f"zero by chance alone; no single month should be called significant on its own.")
    t = ["Each bar is the trend of one calendar month on its own (for example all Januaries), as Sen's slope "
         "per decade."]
    if vals:
        up = max(vals, key=lambda r: r[1])
        dn = min(vals, key=lambda r: r[1])
        clear = [m for m, _, z in vals if z]
        t.append(f"The largest rise is in {up[0]} ({fmt(up[1])} {u} per decade) and the smallest change or "
                 f"largest fall is in {dn[0]} ({fmt(dn[1])} {u} per decade).")
        if clear:
            t.append(f"Months whose 95% range does not include zero: {', '.join(clear)}.")
        t.append(note)
        t.append("Each month has only one value per year, so these trends are much noisier than the full record; "
                 "read the bars as a pattern that shows whether the change is spread over the year or concentrated "
                 "in a season.")
    else:
        t.append("Too few years per month to estimate month-by-month trends.")
    out.append(_sec("seasons", "Which months changed most?", "bars", " ".join(t),
                    {**se, "units": u, "n_tests": n_tests, "expected_by_chance": expect,
                     "multiple_testing_note": note if vals else None},
                    {**base_facts, "direction": direction, "months": dict(zip(MONTHS, se["values"])),
                     "months_ci_excludes_zero": [m for m, _, z in vals if z], "n_tests": n_tests,
                     "expected_by_chance": expect}))

    # 8 map
    tm = c["trend_map"]
    if tm:
        mu = tm["units"] or u
        bb = tm["bbox"]
        neigh = NEIGHBOURS.get((c["region_name"] or "").strip().lower())
        t = [f"The map splits the area into {tm['n_cells']} grid cells of {short_name({'name': tm['variable_name']})} "
             f"and shows the trend of each cell in {mu} per decade ({tm['period'][0][:7]} to {tm['period'][1][:7]}).",
             f"The grid is coarse ({tm.get('spatial_resolution') or 'see dataset documentation'}), so one cell covers "
             f"a whole city and its countryside."]
        if tm["box_around_point"]:
            t.append(f"Your place is a point, so the map shows a {bb[2] - bb[0]:.0f}° wide box around it.")
        elif tm.get("masked_to_region"):
            t.append(f"Cells whose centre lies outside {c['region_name']} were left out.")
        else:
            t.append(f"The map is a rectangle around {c['region_name']} ({num(bb[0], 1)}°E to {num(bb[2], 1)}°E, "
                     f"{num(bb[1], 1)}°N to {num(bb[3], 1)}°N), so it also includes neighbouring areas"
                     + (f" such as {neigh}" if neigh else " and possibly sea") + "; no border or land mask is applied.")
        t += [f"About {num(tm['area_fraction_rising'] * 100, 0)}% of the map area has a significant rising trend and "
              f"{num(tm['area_fraction_falling'] * 100, 0)}% a significant falling trend after the field-significance "
              f"correction ({FIELD_EXPLAIN}).",
              f"The area-mean trend of the map is {fmt(tm['area_mean_slope_per_decade'])} {mu} per decade.",
              "This map is exploratory: neighbouring cells are not independent tests."]
        out.append(_sec("map", "Where inside the region did it change?", "map", " ".join(t), tm,
                        {**base_facts, "direction": direction,
                         "map": {k: tm[k] for k in ("n_cells", "area_fraction_rising", "area_fraction_falling",
                                                    "area_mean_slope_per_decade", "period", "bbox")},
                         "percent_rising": round(tm["area_fraction_rising"] * 100),
                         "percent_falling": round(tm["area_fraction_falling"] * 100),
                         "resolution": tm.get("spatial_resolution"), "neighbours": neigh,
                         "map_text": tm["field_significance"]["plain_language"]}))
    else:
        out.append(_sec("map", "Where inside the region did it change?", "text",
                        (c["map_note"] or "No map could be drawn.") + " The rest of the report uses the area mean.",
                        {"reason": c["map_note"]}, base_facts))

    # 9 context (published research is added after the first view)
    fam = (v.get("family") or "").lower()
    cfacts = {**base_facts, "family_context": FAMILY_CONTEXT.get(fam) or FAMILY_CONTEXT.get(c["vid"].split("_")[-1])
              or ""}
    text, data = _context_text(cfacts, c["research"], direction, pending=c.get("research_pending", False))
    out.append(_sec("context", "What could explain it?", "text", text, data, cfacts))

    # 10 limits
    lim = _limits(c)
    out.append(_sec("limits", "What this cannot tell you", "text", " ".join(lim[:8]), {"limits": lim},
                    {**base_facts, "limits": lim}))
    return out


def engine_limit() -> str:
    from ..active import engine
    return engine.LIMIT


def _limits(c: dict) -> list[str]:
    an, v = c["an"], c["v"]
    out = _limits_clean(list((_verdict(an).get("caveats") or [])[:3]))
    if c["region"].is_point:
        out.append("The series is for one grid cell or station near your point, not the whole surrounding area.")
    else:
        out.append(f"The region is an approximate box around {c['region_name']}; a box can include sea or "
                   f"neighbouring land.")
    if "reanalysis" in (v.get("name") or "").lower() or "reanalysis" in (v.get("definition") or "").lower():
        out.append("This dataset is a reanalysis: a weather model guided by observations, not a direct measurement; "
                   "places with few weather stations are less certain.")
    out.append("A trend over this period describes the past; it is not a forecast.")
    if (c.get("label") or {}).get("label") == "VERIFIED":
        out.append(engine_limit())
    out.append("Explanations are written as 'consistent with' or 'associated with'; this report does not show a cause.")
    if c["trend_map"]:
        out.append("The trend map is exploratory; each cell is not an independent test.")
    return [x for x in dict.fromkeys(out) if x]
