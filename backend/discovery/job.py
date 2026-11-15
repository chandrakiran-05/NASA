"""Discovery job: plan -> sweep -> verify -> literature / preprints / news -> gap flag -> brief.

Runtime is bounded: a time budget (default 300 s) after which no new candidate is started, a cap on
candidates (2 x max_findings per sweep variable plus one per criterion for a named region), and limited
concurrency (2 sweeps, 2 verifications at once). Every finished finding is published as a `finding` event,
so the first useful result arrives long before the job ends. Everything upstream is cached (HTTP cache,
series store, novelty results), so a repeat run is fast.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict
from datetime import date

from ..active import runner as active
from ..active.runner import CRITERIA, EventLog, _ineligible
from ..core.errors import InvalidRequest
from ..core.geometry import Region, parse_geometry
from ..timeseries.service import parse_date
from . import brief as B
from . import sources
from .sweep import (DEFAULT_GLOBAL_CRITERIA, GLOBAL_BOX, OCEAN_CRITERIA, SWEEP_VARIABLES, cell_region, literature_place,
                    sweep_variable)

SWEEP_CONCURRENCY = 2
VERIFY_CONCURRENCY = 2
DEFAULT_BUDGET_S = 300
REGION_SWEEP_MIN_AREA = 100.0          # deg^2: a named region this big is also swept for sub-hotspots
# plain words students use -> criteria ids (the catalog's criterion matcher handles the rest)
WORDS = {"rain": "precipitation", "rainfall": "precipitation", "monsoon": "precipitation",
         "precipitation": "precipitation", "drought": "soil_moisture", "drying": "soil_moisture",
         "soil": "soil_moisture", "vegetation": "vegetation", "greening": "vegetation", "forest": "forest_condition",
         "heat": "temperature", "warming": "temperature", "temperature": "temperature", "snow": "snow_ice",
         "glacier": "snow_ice", "air quality": "atmospheric_composition", "pollution": "atmospheric_composition",
         "aerosol": "atmospheric_composition", "sea ice": "sea_ice", "ocean": "sea_surface_temperature",
         "sst": "sea_surface_temperature", "chlorophyll": "chlorophyll", "plankton": "chlorophyll"}

YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
NOW_RE = re.compile(r"\b(recent|now|today|present|current|latest)\b", re.I)
LONG_REQUEST_YEARS = 40                # asking for this many years or more: use the longest record first

LOGS: OrderedDict[str, EventLog] = OrderedDict()
INFLIGHT: dict[str, str] = {}


def register(job_id: str, log: EventLog, max_logs: int = 50) -> None:
    LOGS[job_id] = log
    while len(LOGS) > max_logs:
        LOGS.popitem(last=False)


class ForwardLog:
    """Lets the active-trend runner stream its steps into the discovery log under one candidate id
    (its own 'done' must not end the discovery stream, so every event is re-typed as 'step')."""

    def __init__(self, log: EventLog, cid: str):
        self.log, self.cid = log, cid

    async def emit(self, kind: str, **payload) -> None:
        if kind in ("fetching", "fetched", "failed", "fallback", "candidate", "not_active", "check", "beast",
                    "verdict"):
            payload.pop("detail", None)
            await self.log.emit("step", candidate_id=self.cid, step=kind, **payload)


async def _noop(_p: float, _m: str) -> None:
    return None


# ------------------------------------------------------------------ planning
def _criteria_from_text(st, text: str) -> list[str]:
    t = (text or "").lower()
    found = [c for w, c in WORDS.items() if w in t]
    matched = st.catalog.match_criteria(text or "")
    # plain words already name what to scan: then only the matcher's clear best adds to them
    for c, score in (matched[:1] if found else matched[:3]):
        if score >= 0.6:
            found.append(c["id"])
    by_id = {c["id"]: c for c in CRITERIA}
    return [c for c in dict.fromkeys(found) if c in by_id and by_id[c]["status"] != "not_trendable"]


def make_plan(st, body: dict) -> dict:
    """Region, criteria and period from the request body and/or the free-text prompt (deterministic planner)."""
    prompt = (body.get("prompt") or "").strip()
    parsed = st.ai._deterministic_plan(prompt) if prompt else None
    last_full = date.today().year - 1
    region, region_name, source = None, body.get("region_name"), None
    if body.get("geometry"):
        region = parse_geometry(body["geometry"])
        source = "request geometry"
    elif body.get("bbox"):
        w, s, e, n = body["bbox"]
        region = Region("bbox", (float(w), float(s), float(e), float(n)), name=region_name)
        source = "request bbox"
    elif parsed and parsed.get("regions"):
        r0 = parsed["regions"][0]
        region = parse_geometry(r0["geometry"])
        region_name = region_name or r0.get("name")
        source = r0.get("source") or "planner"
    if region is not None and region.is_point:              # a point is too small to sweep: use a 5 x 5 deg box
        lon, lat = region.point
        region = Region("bbox", (lon - 2.5, lat - 2.5, lon + 2.5, lat + 2.5), name=region_name)
    if region is not None and region_name and not region.name:
        region = Region(region.kind, region.bbox, point=region.point, polygon=region.polygon, name=region_name)

    by_id = {c["id"]: c for c in CRITERIA}
    criteria = list(body.get("criteria") or [])
    unknown = [c for c in criteria if c not in by_id]
    if unknown:
        raise InvalidRequest(f"Unknown criteria {unknown}; see GET /api/criteria")
    if not criteria and body.get("variables"):
        for vid in body["variables"]:
            criteria += [c["id"] for c in CRITERIA if vid in c["variables"]][:1]
    if not criteria and prompt:
        criteria = _criteria_from_text(st, prompt)
        if not criteria and parsed:
            for v in parsed.get("variables") or []:
                criteria += [c["id"] for c in CRITERIA if v["id"] in c["variables"]][:1]
    criteria = list(dict.fromkeys(criteria)) or list(DEFAULT_GLOBAL_CRITERIA)

    y0, y1 = body.get("start_year"), body.get("end_year")
    per = (parsed or {}).get("period") or {}
    ty0, ty1 = years_from_text(prompt, last_full)
    if not y1:
        y1 = int(per["end"][:4]) if per.get("parsed_from") and per.get("end") else ty1 or last_full
    if not y0:
        y0 = int(per["start"][:4]) if per.get("parsed_from") and per.get("start") else ty0 or y1 - 24
    asked = [y0, y1]
    shift = shift_period(st, _variable_pool(st, criteria, region), y0, y1, last_full)
    if shift:
        y0, y1 = shift["used"]
    if y1 - y0 + 1 < active.engine.MIN_YEARS:
        raise InvalidRequest(f"Discovery needs at least {active.engine.MIN_YEARS} years (got {y0}-{y1})")
    start, end = parse_date(f"{y0}-01"), parse_date(f"{y1}-12", end=True)
    longest = bool(shift) or asked[1] - asked[0] + 1 >= LONG_REQUEST_YEARS

    sweeps, direct, skipped = [], [], []
    for c in criteria:
        crit = by_id[c]
        sv = SWEEP_VARIABLES.get(c)
        if region is None:
            if sv:
                sweeps.append({"criterion": c, "variable_id": sv, "box": GLOBAL_BOX})
            else:
                skipped.append({"criterion": c, "reason": "no keyless global grid for a sweep; name a region "
                                                          "(e.g. 'vegetation in the Sahel') to test it there"})
            continue
        chain = variable_chain(st, crit, region, start, end, prefer_nasa=body.get("prefer_nasa", True),
                               longest=longest)
        if chain:
            direct.append({"criterion": c, "variable_id": chain[0], "variable_ids": chain})
        else:
            skipped.append({"criterion": c, "reason": "no variable of this criterion covers this region and period"})
        if sv and region.area_deg2 >= REGION_SWEEP_MIN_AREA:
            sweeps.append({"criterion": c, "variable_id": sv, "box": tuple(region.bbox)})
    return {"prompt": prompt or None, "mode": "region" if region is not None else "global_sweep",
            "region": region, "region_name": region_name or (region.name if region else None),
            "region_source": source, "criteria": criteria, "start": start, "end": end,
            "years": [y0, y1], "asked_years": asked, "period_notice": shift, "sweeps": sweeps, "direct": direct,
            "skipped": skipped, "planner": (parsed or {}).get("planner"), "prefer_nasa": body.get("prefer_nasa", True)}


def years_from_text(text: str | None, last_full: int) -> tuple[int | None, int | None]:
    """Years the deterministic planner leaves out ('from 1700 to recent'): the first year is the start, a second
    year or a word like 'recent' / 'now' the end."""
    ys = [int(y) for y in YEAR_RE.findall(text or "")]
    y0 = ys[0] if ys else None
    y1 = ys[1] if len(ys) > 1 else (last_full if y0 is not None and NOW_RE.search(text or "") else None)
    if y0 is not None and y1 is not None and y1 < y0:
        y0, y1 = y1, y0
    return y0, (min(y1, last_full) if y1 else None)


def _variable_pool(st, criteria: list[str], region) -> list[str]:
    """Every catalog variable that could serve these criteria here (criterion variables in a region, sweep grids)."""
    by_id = {c["id"]: c for c in CRITERIA}
    out = []
    for c in criteria:
        if region is not None:
            out += [v for v in by_id[c]["variables"] if v in st.catalog.variables and _box_ok(st, v, region)]
        if SWEEP_VARIABLES.get(c):
            out.append(SWEEP_VARIABLES[c])
    return list(dict.fromkeys(out))


def _box_ok(st, vid: str, region) -> bool:
    """A 0..360-longitude ERDDAP grid cannot read a box that crosses 0 deg longitude (e.g. Africa)."""
    v = st.catalog.variables.get(vid, {})
    w, _, e, _ = region.bbox
    return not (v.get("erddap_lon360") and not region.is_point and w < 0 < e)


def _cov(st, vid: str) -> int | None:
    s = (st.catalog.variables.get(vid, {}).get("coverage_start") or "")[:4]
    return int(s) if s.isdigit() else None


def shift_period(st, pool: list[str], y0: int, y1: int, last_full: int) -> dict | None:
    """Asked years start before every record here (no instruments or satellites in these sources then): use the
    longest available record instead and say so in plain words. None when the asked start is covered."""
    starts = sorted((c, v) for v in pool if (c := _cov(st, v)) is not None)
    if not starts or y0 >= starts[0][0]:
        return None
    first, vid = starts[0]
    end = y1 if y1 - first + 1 >= active.engine.MIN_YEARS else last_full
    name = st.catalog.variables[vid].get("name", vid)
    asked = f"{y0}-{y1}" if y1 != y0 else str(y0)
    return {"asked": [y0, y1], "used": [first, end], "earliest_variable_id": vid,
            "plain_language": (f"You asked for {asked}, but no instrument or satellite record in this tool's sources "
                               f"goes back to {y0}. The longest record available here starts in {first} ({name}). "
                               f"Knowledge of earlier centuries comes from tree rings, cave deposits and historical "
                               f"documents, which this tool does not analyse. Using the longest available record "
                               f"instead: {first}-{end}.")}


def variable_chain(st, crit: dict, region, start, end, *, prefer_nasa: bool, longest: bool = False) -> list[str]:
    """Eligible variables of a criterion in the order they are tried (the next one when a source fails).
    Default: NASA products first when a token exists, else keyless first. `longest`: earliest record first."""
    ok = [v for v in crit["variables"] if v in st.catalog.variables
          and not _ineligible(st.catalog.variables[v], region, start, end, {}) and _box_ok(st, v, region)]
    if longest:
        return sorted(ok, key=lambda v: _cov(st, v) or 9999)          # stable: ties keep the criterion order
    if prefer_nasa and st.settings.earthdata_token is not None:
        return ok                                     # criteria list NASA products first
    keyless = [v for v in ok if st.catalog.variables[v].get("source") in ("erddap", "nsidc", "coops", "usgs")]
    return keyless + [v for v in ok if v not in keyless]


def _choose_variable(st, crit: dict, region, start, end, *, prefer_nasa: bool) -> str | None:
    chain = variable_chain(st, crit, region, start, end, prefer_nasa=prefer_nasa)
    return chain[0] if chain else None


def plan_view(p: dict) -> dict:
    return {"prompt": p["prompt"], "mode": p["mode"], "region": p["region"].as_dict() if p["region"] else None,
            "region_name": p["region_name"], "region_source": p["region_source"], "criteria": p["criteria"],
            "years": p["years"], "asked_years": p.get("asked_years", p["years"]),
            "period_notice": p.get("period_notice"), "sweeps": [{k: v for k, v in s.items()} | {"box": list(s["box"])} for s in p["sweeps"]],
            "direct": p["direct"], "skipped": p["skipped"]}


# ------------------------------------------------------------------ the job
async def run(st, log: EventLog, progress, p: dict, *, max_findings: int = 3, budget_s: float = DEFAULT_BUDGET_S,
              alpha: float = 0.05, ai_prose: bool = True, news: bool = True, preprints: bool = True) -> dict:
    t0 = time.monotonic()
    deadline = t0 + budget_s
    start, end = p["start"], p["end"]
    req = {"start": start.strftime("%Y-%m"), "end": end.strftime("%Y-%m"), "alpha": alpha}
    sweep_sem, verify_sem = asyncio.Semaphore(SWEEP_CONCURRENCY), asyncio.Semaphore(VERIFY_CONCURRENCY)
    candidates: list[dict] = []
    findings: list[dict] = []
    sweeps: list[dict] = []
    failed_sources: list[dict] = []
    tasks: list[asyncio.Task] = []
    counter = {"c": 0, "f": 0}
    await log.emit("started", plan=plan_view(p), budget_s=budget_s, max_findings=max_findings,
                   plain_language=_start_text(p, budget_s))

    def new_candidate(region: Region, criterion: str, chain: list[str], why: str) -> dict:
        counter["c"] += 1
        c = {"id": f"c{counter['c']}", "region": region, "criterion": criterion, "variable_id": chain[0],
             "variable_ids": chain, "why": why, "literature_place": literature_place(region.name), "status": "queued"}
        candidates.append(c)
        return c

    async def verify(c: dict) -> None:
        async with verify_sem:
            if len(findings) >= max_findings:
                c.update(status="skipped", reason="enough findings already")
                await log.emit("candidate_skipped", candidate_id=c["id"], reason=c["reason"])
                return
            if time.monotonic() > deadline:
                c.update(status="skipped", reason=f"time budget of {budget_s:.0f} s reached")
                await log.emit("candidate_skipped", candidate_id=c["id"], reason=c["reason"])
                return
            c["status"] = "verifying"
            await log.emit("verifying", candidate_id=c["id"], variable_id=c["variable_id"], place=c["region"].name)
            res, last = None, None
            for k, vid in enumerate(c["variable_ids"]):       # the next source when one cannot be read
                if k:
                    await log.emit("step", candidate_id=c["id"], step="fallback", variable_id=vid,
                                   instead_of=c["variable_ids"][k - 1], reason=str(last)[:200])
                try:
                    res = await active.run(st, ForwardLog(log, c["id"]), _noop,
                                           items=[{"variable_id": vid, "criteria": []}],
                                           region=c["region"], start=start, end=end, alpha=alpha, ai_review=False,
                                           options={}, research=False, region_name=c["literature_place"])
                except Exception as exc:  # noqa: BLE001
                    res, last = None, getattr(exc, "message", str(exc))
                    continue
                if res["trends"] or res["not_active"]:
                    c["variable_id"] = vid
                    break
                last = "; ".join(f"{k}: {v}" for k, v in res["failed"].items()) or "no series"
            if res is None or not (res["trends"] or res["not_active"]):
                c.update(status="failed", reason=f"No data source could be read for this place ({str(last)[:260]})")
                await log.emit("candidate_rejected", candidate_id=c["id"], reason=c["reason"])
                return
            keep = [t for t in res["trends"] if t["verdict"]["label"] in ("VERIFIED", "PROBABLE")]
            if not keep:
                card = await tested_card(st, c, res, alpha)
                c.update(status="rejected", reason=((card or {}).get("reason") or "did not pass verification")[:400],
                         tested=card)
                await log.emit("candidate_rejected", candidate_id=c["id"], reason=c["reason"],
                               label=res["trends"][0]["verdict"]["label"] if res["trends"] else "NOT VERIFIED")
                if card:
                    await log.emit("tested", card=card)
                return
            if len(findings) >= max_findings:
                c.update(status="skipped", reason="enough findings already")
                return
            counter["f"] += 1
            fid = f"f{counter['f']}"
            c.update(status="finding", finding_id=fid)
            br = await write_up(st, log, c, keep[0], fid, req, ai_prose=ai_prose, news=news, preprints=preprints)
            findings.append(br)
            failed_sources.extend({"finding_id": fid, **s} for s in _failed_sources(br))
            await log.emit("finding", finding=br)
            await progress(min(0.95, 0.3 + 0.65 * len(findings) / max(max_findings, 1)),
                           f"{len(findings)} finding(s) written")

    async def do_sweep(s: dict) -> None:
        async with sweep_sem:
            await log.emit("sweep_started", criterion=s["criterion"], variable_id=s["variable_id"],
                           box=list(s["box"]))
            res = await sweep_variable(st, s["criterion"], s["variable_id"], s["box"], start, end, alpha=alpha,
                                       k=max(2, max_findings))
        sweeps.append(res)
        await log.emit("sweep", **{k: v for k, v in res.items() if k != "grids"},
                       area_fraction_rising=[g["area_fraction_rising"] for g in res["grids"]],
                       area_fraction_falling=[g["area_fraction_falling"] for g in res["grids"]])
        if res["status"] != "ok":
            failed_sources.append({"source": f"NOAA ERDDAP grid: {res.get('name') or s['variable_id']}",
                                   "status": "unavailable", "reason": res.get("reason") or "no answer"})
            return
        chain = _sweep_followup_variable(st, s["criterion"], s["variable_id"], start, end, p.get("prefer_nasa", True))
        for cell in res["cells"]:
            reg = cell_region(cell, ocean=s["criterion"] in OCEAN_CRITERIA)
            c = new_candidate(reg, s["criterion"], chain(reg),
                              f"sweep cell {cell['lat']:.1f}, {cell['lon']:.1f}: {cell['slope_per_decade']:+.3g} "
                              f"{res.get('units') or ''} per decade (exploratory)")
            await log.emit("candidate", candidate_id=c["id"], criterion=c["criterion"], variable_id=c["variable_id"],
                           place=reg.name, bbox=list(reg.bbox), why=c["why"])
            tasks.append(asyncio.ensure_future(verify(c)))

    for d in p["direct"]:
        c = new_candidate(p["region"], d["criterion"], d.get("variable_ids") or [d["variable_id"]],
                          "the whole region you named")
        await log.emit("candidate", candidate_id=c["id"], criterion=c["criterion"], variable_id=c["variable_id"],
                       place=p["region"].name, bbox=list(p["region"].bbox), why=c["why"])
        tasks.append(asyncio.ensure_future(verify(c)))
    await progress(0.05, "Scanning")
    await asyncio.gather(*(do_sweep(s) for s in p["sweeps"]))
    while tasks:                                   # verifications can be added while sweeps finish
        pending, tasks[:] = list(tasks), []
        await asyncio.gather(*pending)

    n_pot = sum(bool(f["potential_discovery"]) for f in findings)
    elapsed = round(time.monotonic() - t0, 1)
    tested = [c["tested"] for c in candidates if c.get("tested")]
    out = {
        "plan": plan_view(p),
        "sweeps": sweeps,
        "candidates": [candidate_view(c) for c in candidates],
        "findings": findings,
        "tested": tested,
        "failed_sources": [{**s, "text": f"{s['source']}: {s.get('reason') or s.get('status') or 'no answer'}"}
                           for s in failed_sources if s.get("source")],
        "summary": {"candidates": len(candidates), "findings": len(findings),
                    "verified": sum(f["verdict"]["label"] == "VERIFIED" for f in findings),
                    "probable": sum(f["verdict"]["label"] == "PROBABLE" for f in findings),
                    "potential_new_findings": n_pot},
        "timing": {"elapsed_s": elapsed, "budget_s": budget_s},
        "plain_language": run_summary(len(candidates), len(findings), n_pot, len(tested)),
        "next_steps": None if findings else NEXT_STEPS,
        "limits": [active.engine.LIMIT, B.GAP_RULE,
                   "The sweep is exploratory and coarse (one cell of a strided global grid); it only nominates places.",
                   "Drivers are associations (PCMCI+), never proof of a cause.",
                   "Outlooks are " + B.OUTLOOK_LABEL + "; preprints and news are not peer reviewed."],
    }
    await log.emit("done", summary=out["summary"], plain_language=out["plain_language"], timing=out["timing"])
    return out


NEXT_STEPS = ("What you can try: a longer period, a smaller region (for example one country or basin), or another "
              "variable such as temperature, soil moisture or vegetation.")


def run_summary(n_cand: int, n_found: int, n_pot: int, n_tested: int) -> str:
    if n_found:
        return (f"Tested {n_cand} candidate place(s); {n_found} passed verification (VERIFIED or PROBABLE) and {n_pot} "
                f"of those have no matching published study in the searched sources (potential new finding, not yet "
                f"checked by scientists).")
    if n_tested:
        return (f"None of the {n_cand} tested place(s) passed verification, so there is no finding to write up. The "
                f"data shown below are real; only the trend test was inconclusive for them.")
    if n_cand:
        return f"{n_cand} candidate place(s) were found, but their data could not be read, so nothing was tested."
    return "No candidate place could be tested: the data sources for this request did not answer."


def candidate_view(c: dict) -> dict:
    status = {"finding": "passed verification", "rejected": "not kept", "failed": "could not be read",
              "skipped": "not tested", "queued": "not tested", "verifying": "not finished"}.get(c["status"], c["status"])
    place = c["region"].name or "the chosen region"
    return {"id": c["id"], "criterion": c["criterion"], "variable_id": c["variable_id"], "place": place,
            "bbox": list(c["region"].bbox), "why": c["why"], "status": c["status"], "reason": c.get("reason"),
            "finding_id": c.get("finding_id"),
            "text": f"{place} ({c['variable_id']}): {status}" + (f". {c['reason']}" if c.get("reason") else "")}


async def tested_card(st, c: dict, res: dict, alpha: float) -> dict | None:
    """A place that did not pass: its real series and the engine's numbers, so the student still sees what the data
    say. Only cached engine results are re-read here (detection and analysis); nothing new is computed."""
    from ..api import pipeline
    try:
        if res["trends"]:
            tr = res["trends"][0]
            vid, name, sid = tr["variable_id"], tr["name"], tr["series_id"]
            det, verdict, beast, view = tr["detect"], tr["verdict"], tr.get("beast"), tr.get("view")
            checks = tr.get("checks")
        else:
            na = res["not_active"][0]
            vid, name, sid = na["variable_id"], na["name"], na["series_id"]
            det = await pipeline.cached_novelty(st, "active_detect", sid, lambda ms: active.engine.detect(ms, alpha),
                                                {"alpha": alpha})
            verdict = beast = checks = None
            try:
                an = await pipeline.cached_analysis(st, sid, alpha=alpha)
                ch = an.get("chart") or {}
                view = {"units": an.get("units"), "markers": [],
                        "chart": {"time": ch.get("time"), "observed": ch.get("raw"),
                                  "deseasonalized": ch.get("deseasonalized"), "sen_line": ch.get("sen_line")}}
            except Exception:  # noqa: BLE001 - too short to analyse: numbers without a chart
                view = None
        prov = st.store.load(sid).provenance.to_dict()
    except Exception:  # noqa: BLE001 - the card is a courtesy; the rejection reason is still reported
        return None
    return B.tested_card(cand=c, variable_id=vid, name=name, det=det, verdict=verdict, beast=beast, view=view,
                         provenance=prov, series_id=sid, checks=checks)


def _sweep_followup_variable(st, criterion: str, sweep_vid: str, start, end, prefer_nasa: bool):
    """The proper series for a nominated cell, as a chain tried in order: a NASA product of the same criterion when
    a token exists (independent of the sweep grid), then the keyless sweep variable itself."""
    crit = next(c for c in CRITERIA if c["id"] == criterion)

    def pick(region):
        if not prefer_nasa:
            return [sweep_vid]
        return list(dict.fromkeys([*variable_chain(st, crit, region, start, end, prefer_nasa=True), sweep_vid]))
    return pick


def _failed_sources(br: dict) -> list[dict]:
    out = []
    for block in (br["literature"], br["preprints"], br["news"]):
        out += [s for s in block.get("sources", []) if s.get("status") == "unavailable"]
    return out


def _start_text(p: dict, budget: float) -> str:
    where = p["region_name"] or ("the region you drew" if p["region"] else "the whole globe (coarse grid)")
    return (f"Scanning {where} for {', '.join(p['criteria'])} over {p['years'][0]}-{p['years'][1]}. "
            f"Time budget about {budget:.0f} s; findings appear as soon as each one is checked.")


async def write_up(st, log: EventLog, c: dict, tr: dict, fid: str, req: dict, *, ai_prose: bool, news: bool,
                   preprints: bool) -> dict:
    from ..research.evidence import research_evidence
    place = c["literature_place"]
    direction = tr["detect"].get("direction", "flat")
    since_year = date.today().year - st.settings.research_max_age_years
    await log.emit("checking_literature", candidate_id=c["id"], finding_id=fid, place=place)

    async def lit():
        try:
            return await asyncio.wait_for(research_evidence(
                st.http, st.llm, variable_id=tr["variable_id"], variable_name=tr["name"], region_name=place,
                direction=direction, max_age_years=st.settings.research_max_age_years,
                per_source=st.settings.research_per_source, springer_key=st.settings.springer_api_key,
                semantic_key=st.settings.semantic_scholar_api_key, ads_token=st.settings.ads_api_token,
                ai_reads=2 if ai_prose else 0), 90)
        except Exception as exc:  # noqa: BLE001
            return {"status": "unavailable", "reason": type(exc).__name__, "sources": [], "papers": []}

    async def pre():
        if not preprints:
            return {"status": "not_run", "items": [], "sources": [], "label": sources.PREPRINT_LABEL}
        try:
            return await sources.preprints(st.http, variable_id=tr["variable_id"], variable_name=tr["name"],
                                           place=place, since_year=since_year, direction=direction)
        except Exception as exc:  # noqa: BLE001
            return {"status": "unavailable", "items": [], "label": sources.PREPRINT_LABEL,
                    "sources": [{"source": "preprints", "status": "unavailable", "reason": type(exc).__name__}]}

    async def nws():
        if not news:
            return {"status": "not_run", "items": [], "sources": [], "label": sources.NEWS_LABEL}
        return await sources.news(st.http, variable_id=tr["variable_id"], variable_name=tr["name"], place=place,
                                  criterion=c["criterion"])

    async def drv():
        try:
            return await B.drivers(st, target_sid=tr["series_id"], target_name=tr["name"],
                                   target_vid=tr["variable_id"], criterion=c["criterion"], region=c["region"],
                                   start=parse_date(req["start"]), end=parse_date(req["end"], end=True))
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "links": [], "reason": type(exc).__name__,
                    "plain_language": "The driver screen could not run."}

    research, pr, nw, dr = await asyncio.gather(lit(), pre(), nws(), drv())
    from starlette.concurrency import run_in_threadpool
    ms = st.store.load(tr["series_id"])
    out = await run_in_threadpool(B.outlook, ms, tr["name"])
    b = B.build_brief(finding_id=fid, cand=c, trend=tr, research=research, pre=pr, nw=nw, drv=dr, out=out,
                      provenance=ms.provenance.to_dict(), request=req)
    if ai_prose:
        b["summary"] = await B.ai_summary(st, B.facts_for(b), b["summary"]["text"])
    return b
