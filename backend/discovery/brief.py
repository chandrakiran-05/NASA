"""Stages 4-5: flag the gaps and write the brief for one verified/probable finding.

Every number in a brief comes from the engines (active-trend detect/verdict, BEAST, PCMCI+, twin
simulation). Optional local-LLM prose is kept only if it passes ai.verify.verify_text against the same
facts and the wording guard below; otherwise the template text is used.
"""
from __future__ import annotations

import asyncio
import json
import re

import numpy as np
import pandas as pd
from starlette.concurrency import run_in_threadpool

POTENTIAL_LABEL = "Potential new finding, not yet checked by scientists"
GAP_RULE = ("Flagged when the data trend is VERIFIED or PROBABLE, the literature sources answered, and none of the "
            "relevant peer-reviewed studies found names this place. It means 'no matching published study found in "
            "the searched sources', not that nobody has studied it.")
OUTLOOK_LABEL = "simulated, statistical extrapolation, not a prediction"
OUTLOOK_DISCLAIMER = ("Simulated from this observed series with the DigiTwin engine (linear trend + AR(1) noise, no "
                      "scenario knobs): not observations and not a climate projection. It only shows what the data till "
                      "today imply if nothing changes.")
UNREVIEWED_LABEL = "Not peer reviewed: preprints and news are early signals, not checked evidence"
# generated text must never claim causes, predictions or confirmed discoveries
FORBIDDEN = re.compile(r"\b(caused by|because of|driven by|proves?|proven|predict(?:s|ed|ion)?|forecast\w*|"
                       r"confirmed discovery|discovery confirmed|will (?:keep|continue|be|reach|rise|fall))\b", re.I)
ALLOWED_NEGATION = re.compile(r"not a prediction", re.I)
# claims about studies or novelty cannot be number-checked: the gap sentence stays template text
UNCHECKABLE = re.compile(r"\b(stud(?:y|ies)|paper|peer|literature|publish\w*|discover\w*|new finding|scientists?)\b", re.I)

# candidate drivers per criterion: keyless gridded series for the same box (cheap, no token needed)
DRIVER_CANDIDATES = {
    "temperature": ["global_soil_moisture", "global_humidity", "global_precip_chirps"],
    "atmospheric_temperature": ["global_soil_moisture", "global_humidity"],
    "precipitation": ["global_t2m", "global_humidity"],
    "soil_moisture": ["global_precip_chirps", "global_t2m", "global_humidity"],
    "land_surface_conditions": ["global_precip_chirps", "global_t2m"],
    "agricultural_conditions": ["global_precip_chirps", "global_t2m"],
    "vegetation": ["global_soil_moisture", "global_precip_chirps", "global_t2m"],
    "forest_condition": ["global_soil_moisture", "global_precip_chirps", "global_t2m"],
    "evaporation": ["global_t2m", "global_soil_moisture"],
    "snow_ice": ["global_t2m", "global_precip_chirps"],
    "sea_surface_temperature": ["global_t2m", "global_humidity"],
    "chlorophyll": ["sst"],
    "atmospheric_composition": ["global_precip_chirps", "global_t2m", "global_humidity"],
}
DRIVER_FETCH_TIMEOUT_S = 90.0


def wording_ok(text: str) -> bool:
    return not FORBIDDEN.search(ALLOWED_NEGATION.sub("", text or ""))


# ------------------------------------------------------------------ gap flag
def gap_flag(research: dict | None, place: str | None) -> dict:
    if not research or research.get("status") == "unavailable":
        return {"potential_discovery": None, "label": None, "rule": GAP_RULE,
                "plain_language": "The literature could not be searched, so no gap flag was set."}
    if not any(s.get("status") == "ok" for s in research.get("sources", [])):
        return {"potential_discovery": None, "label": None, "rule": GAP_RULE,
                "plain_language": "None of the literature sources answered, so no gap flag was set."}
    if not place:
        return {"potential_discovery": None, "label": None, "rule": GAP_RULE,
                "plain_language": "This grid box has no place name the literature search can use, so no gap flag "
                                  "was set."}
    papers = research.get("papers") or []
    matching = [p for p in papers if p.get("peer_reviewed") and p.get("region_match")]
    if matching:
        return {"potential_discovery": False, "label": None, "rule": GAP_RULE, "matching_studies": len(matching),
                "plain_language": f"{len(matching)} peer-reviewed stud{'y' if len(matching) == 1 else 'ies'} in the "
                                  f"searched sources already cover{'s' if len(matching) == 1 else ''} this variable "
                                  f"in {place}."}
    return {"potential_discovery": True, "label": POTENTIAL_LABEL, "rule": GAP_RULE, "matching_studies": 0,
            "plain_language": f"No matching published study found: none of the relevant peer-reviewed studies in the "
                              f"searched sources names {place}. {POTENTIAL_LABEL}."}


def related_works(research: dict | None, n: int = 6) -> list[dict]:
    out = []
    for p in (research or {}).get("papers") or []:
        out.append({k: p.get(k) for k in ("title", "year", "venue", "doi", "url", "source", "peer_reviewed",
                                          "stance", "region_match", "trust")}
                   | {"doi_url": f"https://doi.org/{p['doi']}" if p.get("doi") else None,
                      "label": "peer reviewed" if p.get("peer_reviewed") else "not peer reviewed"})
    return out[:n]


# ------------------------------------------------------------------ drivers (PCMCI+)
async def drivers(st, *, target_sid: str, target_name: str, target_vid: str, criterion: str | None, region,
                  start, end) -> dict:
    from ..insights.causal import causal_screen
    cands = [v for v in DRIVER_CANDIDATES.get(criterion or "", []) if v != target_vid and v in st.catalog.variables][:3]
    if not cands:
        return {"status": "not_run", "links": [], "plain_language": "No candidate driver series are set up for this "
                                                                    "kind of variable."}

    async def fetch(vid):
        try:
            info = await asyncio.wait_for(st.ts.build_series(vid, region, start, end), DRIVER_FETCH_TIMEOUT_S)
            return vid, st.store.load(info["series_id"]), None
        except Exception as exc:  # noqa: BLE001 - one missing driver must not stop the others
            return vid, None, getattr(exc, "message", None) or type(exc).__name__

    got = await asyncio.gather(*(fetch(v) for v in cands))
    failed = [{"variable_id": v, "reason": str(r)[:200]} for v, ms, r in got if ms is None]
    series = [ms for _, ms, _ in got if ms is not None]
    if not series:
        return {"status": "unavailable", "links": [], "failed": failed,
                "plain_language": "No candidate driver series could be fetched for this place."}
    target = st.store.load(target_sid)
    try:
        res = await run_in_threadpool(causal_screen, target, series, tau_max=3, alpha=0.05)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "links": [], "failed": failed, "reason": type(exc).__name__,
                "plain_language": "The driver screen could not run on these series."}
    names = {ms.variable_id: st.catalog.variables.get(ms.variable_id, {}).get("name", ms.variable_id) for ms in series}
    links = []
    for lk in res.get("best_per_driver", []):
        dn = names.get(lk["driver"], lk["driver"])
        lag = lk["lag_months"]
        when = "in the same month" if lag == 0 else f"{lag} month{'s' if lag > 1 else ''} earlier"
        if lk.get("significant"):
            txt = (f"{target_name} anomalies are associated with {dn} anomalies {when} "
                   f"(partial r = {lk['partial_r']:+.2f}, FDR p = {lk['p_fdr']:.3f})"
                   + ("; the link holds in both halves of the record." if lk.get("robust_both_halves") else "."))
        else:
            txt = f"No significant association between {target_name} and {dn} anomalies at lags 0-3 months."
        links.append({"driver_id": lk["driver"], "driver_name": dn, "lag_months": lag, "partial_r": lk["partial_r"],
                      "p_fdr": lk.get("p_fdr"), "significant": lk.get("significant"),
                      "robust_both_halves": lk.get("robust_both_halves"), "plain_language": txt})
    sig = [lk for lk in links if lk["significant"]]
    return {"status": res.get("status"), "method": res.get("method"), "links": links, "failed": failed,
            "n_months_common": res.get("n_months_common"), "explains": res.get("explains"),
            "disclaimer": res.get("disclaimer") or "Association evidence, not proof of a cause.",
            "citations": res.get("citations", []),
            "plain_language": (res.get("plain_language") if res.get("status") == "insufficient_overlap" else
                               ("Consistent with " + ", ".join(lk["driver_name"] for lk in sig) +
                                " (association, not a cause)." if sig else
                                "No candidate driver shows a significant association."))}


# ------------------------------------------------------------------ simulated outlook (digital twin engine)
def outlook(ms, name: str, horizon_years: int = 25, n_runs: int = 300) -> dict:
    from ..twin.engine import simulate
    fit = "the record after its last detected trend break (PELT)"
    try:                       # the current regime: fit the trend after the last PELT break, else the full record
        sim = simulate({name: ms}, {name: {"fit_since_year": "auto"}}, horizon_years=horizon_years, n_runs=n_runs,
                       return_runs=True)
    except Exception:  # noqa: BLE001
        fit = "the full record"
        try:
            sim = simulate({name: ms}, {}, horizon_years=horizon_years, n_runs=n_runs, return_runs=True)
        except Exception as exc:  # noqa: BLE001 - too short to fit a baseline, etc.
            return {"status": "not_run", "label": OUTLOOK_LABEL, "disclaimer": OUTLOOK_DISCLAIMER,
                    "reason": getattr(exc, "message", type(exc).__name__)}
    r = sim["variables"][name]
    vals = r.pop("_runs")
    t = pd.DatetimeIndex(pd.to_datetime(r["time"], format="%Y-%m"))
    years = sorted(set(t.year))
    full = [y for y in years if (t.year == y).sum() == 12]
    ann = np.stack([vals[:, t.year == y].mean(axis=1) for y in full], axis=1) if full else np.zeros((n_runs, 0))
    p05, p50, p95 = (np.percentile(ann, q, axis=0) if full else [] for q in (5, 50, 95))
    b = r["baseline"]
    return {"status": "ok", "label": OUTLOOK_LABEL, "disclaimer": OUTLOOK_DISCLAIMER, "kind": "annual mean, simulated",
            "fitted_on": fit,
            "time": [f"{y}-07" for y in full], "years": full,
            "p05": [round(float(x), 6) for x in p05], "p50": [round(float(x), 6) for x in p50],
            "p95": [round(float(x), 6) for x in p95], "units": ms.units, "n_runs": n_runs,
            "horizon_years": horizon_years, "last_observed": b.get("last_observed"),
            "baseline_slope_per_decade": b.get("slope_per_decade"),
            "plain_language": (f"Simulated, not a prediction: if the trend fitted on {fit} ({b.get('slope_per_decade'):+.3g} "
                               f"{ms.units or 'units'} per decade) and the month-to-month noise persist, the 5-95% "
                               f"range of the simulated annual mean in {full[-1] if full else '?'} is "
                               f"{p05[-1]:.3g} to {p95[-1]:.3g} {ms.units or ''}. This is a statistical "
                               f"extrapolation from the data till today."
                               if full else "Simulated outlook unavailable.").replace("  ", " ")}


def unreviewed_context(pre: dict, nw: dict, direction: str, var: str, place: str | None) -> dict:
    where = f" in {place}" if place else ""
    n_pre, n_news = len(pre.get("items", [])), len(nw.get("items", []))
    same = sum(i.get("stance") == direction for i in pre.get("items", []))
    opp = sum(i.get("stance") in ("rising", "falling") and i.get("stance") != direction for i in pre.get("items", []))
    parts = []
    if pre.get("status") != "ok":
        parts.append("Preprint servers could not be searched.")
    elif n_pre:
        parts.append(f"{n_pre} recent preprint{'s' if n_pre != 1 else ''} mention {var}{where}; by keyword reading of "
                     f"the abstracts, {same} describe the same direction and {opp} the opposite.")
    else:
        parts.append(f"No recent preprints on {var}{where} were found.")
    if nw.get("status") != "ok":
        parts.append("News search was unavailable.")
    elif n_news:
        latest = max((i.get("date") or "" for i in nw["items"]), default="")
        parts.append(f"{n_news} news report{'s' if n_news != 1 else ''} from the last months mention it"
                     + (f" (latest {latest})." if latest else "."))
    else:
        parts.append("No recent news reports were found.")
    return {"label": UNREVIEWED_LABEL, "plain_language": " ".join(parts), "n_preprints": n_pre, "n_news": n_news,
            "n_preprints_same_direction": same, "n_preprints_opposite": opp}


# ------------------------------------------------------------------ text
def template_summary(f: dict) -> str:
    since = f["since"]["date"] if f.get("since") else None
    txt = (f"{f['variable']['name']} in {f['where']['name']}: {f['detect_plain_language']} "
           f"Verdict {f['verdict']['label']} ({f['verdict']['why']}).")
    if since:
        txt += f" BEAST dates the start of the current regime to about {since}."
    txt += " " + f["gap"]["plain_language"]
    return txt


async def ai_summary(st, facts: dict, reference: str) -> dict:
    """Optional local-LLM rewrite for students; kept only if every number traces to FACTS and the wording
    passes (verify_text + the guard above). Otherwise the template text."""
    from ..ai.verify import verify_text
    base = {"text": reference, "source": "template", "label": "template text from computed results"}
    msgs = [{"role": "system", "content": (
        "Rewrite the data part of the REFERENCE for a 15-year-old in at most 3 short sentences. Use only numbers "
        "from FACTS, always with their units, and keep the verdict label word for word. Do not mention studies, "
        "papers or discoveries. Never claim a cause (say 'associated with'), never call anything a prediction.")},
            {"role": "user", "content": "FACTS:\n" + json.dumps(facts, default=str) + "\n\nREFERENCE:\n" + reference}]
    try:
        out = await asyncio.wait_for(st.llm.chat(msgs, max_tokens=200), 60)
    except Exception:  # noqa: BLE001 - template stays
        return base
    out = (out or "").strip()
    if len(out) < 40 or not wording_ok(out) or UNCHECKABLE.search(out):
        return base
    if facts.get("units") and facts["units"] not in out:          # rate without its units is not kept
        return base
    if facts.get("label") and facts["label"] not in out:          # the verdict label must stay visible
        return base
    v = verify_text(out, facts)
    if not v["passed"]:
        return base
    return {"text": out, "source": "local_llm", "label": "AI-written, number-checked", "badge": v["badge"]}


def figure(view: dict | None, beast: dict | None, detect: dict) -> dict:
    ch = (view or {}).get("chart") or {}
    since = (beast or {}).get("active_since") or {}
    return {"time": ch.get("time"), "observed": ch.get("observed"), "deseasonalized": ch.get("deseasonalized"),
            "sen_line": ch.get("sen_line"), "beast_trend": ch.get("beast_trend"), "units": (view or {}).get("units"),
            "change_date": since.get("date"), "change_interval90": since.get("interval90"),
            "recent_window": detect.get("recent_window"), "markers": (view or {}).get("markers", [])}


def build_brief(*, finding_id: str, cand: dict, trend: dict, research: dict | None, pre: dict, nw: dict,
                drv: dict, out: dict, provenance: dict | None, request: dict) -> dict:
    det, verdict, beast = trend["detect"], trend["verdict"], trend.get("beast") or {}
    since = beast.get("active_since")
    place = cand["region"].name or "the chosen region"
    lit_place = cand.get("literature_place")
    direction = det.get("direction", "flat")
    word = {"rising": "rising", "falling": "falling"}.get(direction, "changing")
    w0, w1 = det["recent_window"]["start"][:4], det["recent_window"]["end"][:4]
    gap = gap_flag(research, lit_place)
    b = {
        "finding_id": finding_id, "candidate_id": cand["id"],
        "title": f"{trend['name']} {word} in {place.split(' (')[0]}, {w0}-{w1}",
        "potential_discovery": gap["potential_discovery"], "discovery_label": gap["label"], "gap": gap,
        "variable": {"id": trend["variable_id"], "name": trend["name"], "criterion": cand.get("criterion"),
                     "units": det.get("units")},
        "where": {"name": place, "geometry": cand["region"].as_dict(), "bbox": list(cand["region"].bbox),
                  "approximate": True, "nominated_by": cand.get("why")},
        "what": det["plain_language"], "detect_plain_language": det["plain_language"],
        "since": ({"date": since["date"], "interval90": since.get("interval90"), "probability": since.get("probability"),
                   "source": "BEAST change point (current regime)", "agrees_with_pelt": since.get("agrees_with_pelt")}
                  if since else None),
        "rate": {"per_decade": det.get("rate_per_decade"), "units": det.get("units"),
                 "window": det.get("recent_window"), "ci95_per_decade": (det.get("recent") or {}).get("ci95_per_decade"),
                 "plain_language": f"{det.get('rate_per_decade'):+.3g} {det.get('units') or 'units'} per decade over "
                                   f"{det['recent_window']['start']} to {det['recent_window']['end']}"},
        "verdict": {"label": verdict["label"], "why": verdict["why"], "limit": verdict["limit"],
                    "plain_language": verdict["plain_language"], "test_note": verdict.get("test_note"),
                    "data_note": verdict.get("data_note")},
        "checks": [{"check": c["check"], "status": c["status"], "plain_language": c["plain_language"]}
                   for c in trend.get("checks", [])],
        "beast": {"status": beast.get("status"), "plain_language": beast.get("plain_language")},
        "drivers": drv,
        "literature": {"status": (research or {}).get("status", "ok" if research else "unavailable"),
                       "query": (research or {}).get("query"), "sources": (research or {}).get("sources", []),
                       "agreement": ((research or {}).get("agreement") or {}).get("label"),
                       "plain_language": (research or {}).get("plain_language"),
                       "related_works": related_works(research), "limits": (research or {}).get("limits", [])},
        "preprints": pre, "news": nw,
        "figure": figure(trend.get("view"), beast, det),
        "outlook": {**out, "unreviewed_context": unreviewed_context(pre, nw, direction, trend["name"], lit_place)},
        "provenance": provenance,
        "series_id": trend["series_id"],
        "reproduce": {"variable_id": trend["variable_id"], "geometry": cand["region"].as_dict(),
                      "start": request["start"], "end": request["end"], "alpha": request["alpha"],
                      "series_id": trend["series_id"], "driver_ids": [lk["driver_id"] for lk in drv.get("links", [])],
                      "direction": direction, "region_name": lit_place},
        "limits": [verdict["limit"], GAP_RULE,
                   "Drivers are associations from PCMCI+, consistent with an influence, never proof of a cause.",
                   "The outlook is " + OUTLOOK_LABEL + "."],
        "wording": {"verdict": "VERIFIED / PROBABLE + limit", "drivers": "associated with / consistent with",
                    "outlook": OUTLOOK_LABEL, "gap": POTENTIAL_LABEL},
    }
    b["summary"] = {"text": template_summary(b), "source": "template", "label": "template text from computed results"}
    return b


TESTED_NOTE = ("The data are real; only the trend test was inconclusive here, so this place is not a finding. "
               "NOT VERIFIED does not mean that nothing is changing.")


def tested_card(*, cand: dict, variable_id: str, name: str, det: dict, verdict: dict | None, beast: dict | None,
                view: dict | None, provenance: dict | None, series_id: str, checks: list | None = None) -> dict:
    """A tested place that did not pass verification: series + the engine's numbers + the plain reason."""
    from ..active.engine import LIMIT
    rw = det.get("recent_window") or {}
    r, u = det.get("rate_per_decade"), det.get("units") or "units"
    full = det.get("full") or {}
    fig = figure(view, beast, det) if view else None
    t = (fig or {}).get("time") or []
    return {
        "candidate_id": cand["id"], "place": cand["region"].name or "the chosen region",
        "criterion": cand.get("criterion"), "series_id": series_id,
        "variable": {"id": variable_id, "name": name, "units": det.get("units")},
        "label": (verdict or {}).get("label") or "NOT VERIFIED", "state": det.get("state"),
        "reason": (verdict or {}).get("plain_language") or det.get("plain_language"),
        "why": (verdict or {}).get("why"),
        "rate": ({"per_decade": r, "units": det.get("units"), "window": rw,
                  "ci95_per_decade": (det.get("recent") or {}).get("ci95_per_decade"),
                  "significant": (det.get("recent") or {}).get("significant"),
                  "plain_language": f"{r:+.3g} {u} per decade over {rw.get('start')} to {rw.get('end')}"}
                 if r is not None else None),
        "full_record": ({"per_decade": full["slope_per_decade"], "significant": full.get("significant"),
                         "plain_language": f"{full['slope_per_decade']:+.3g} {u} per decade over the whole record"
                                           f" ({'significant' if full.get('significant') else 'not significant'})"}
                        if full.get("slope_per_decade") is not None else None),
        "period": [t[0][:7], t[-1][:7]] if t else None,
        "figure": fig, "provenance": provenance,
        "checks": [{"check": c["check"], "status": c["status"], "plain_language": c["plain_language"]}
                   for c in (checks or [])],
        "limit": (verdict or {}).get("limit") or LIMIT, "note": TESTED_NOTE,
    }


def facts_for(b: dict) -> dict:
    years = [int(b["rate"]["window"]["start"][:4]), int(b["rate"]["window"]["end"][:4])]
    if b.get("since"):
        years.append(int(b["since"]["date"][:4]))
    return {"variable": b["variable"]["name"], "place": b["where"]["name"],
            "direction": "rising" if (b["rate"]["per_decade"] or 0) > 0 else "falling", "significant": True,
            "rate_per_decade": b["rate"]["per_decade"], "units": b["rate"]["units"], "years": years,
            "label": b["verdict"]["label"], "potential_new_finding": b["potential_discovery"]}
