"""Research Evidence: does recent published research back the trend the data show?

Pipeline for one verified/probable trend (variable, region, direction):
1. Query     variable terms + region + "trend" -> arXiv, OpenAlex, Springer Nature (literature.py),
             restricted to the last `max_age_years` years.
2. Relevance deterministic score: variable term in title/abstract, region named, trend language,
             recency. Papers below the threshold are dropped (never shown as evidence).
3. Reading   each abstract's stance on the variable's direction is read by a deterministic lexicon
             (sentence must name the variable). Optionally the local AI reads it too, but its reading
             is accepted ONLY if it quotes a sentence that occurs verbatim in the abstract and that
             sentence itself contains wording for the claimed direction. Otherwise it is discarded as
             unsupported ("AI slop" guard) and the deterministic reading stands.
4. Agreement weights = relevance x region match x recency. supported / conflicts / mixed / none.

Choosing the best trend (`choose_best`) combines the data verdict (VERIFIED needs BEAST agreement,
see active/engine.py), the size of the change, and research agreement. NOT VERIFIED trends are never
chosen, whatever the literature says: research context cannot rescue data that fail verification.
"""
from __future__ import annotations

import math
import re
from datetime import date

from . import literature

# variable family -> search/reading terms (first term is used in the query)
TERMS = [
    (("ndvi", "evi", "gpp"), ["NDVI", "vegetation greenness", "vegetation index", "greening", "browning", "vegetation"]),
    (("lst",), ["land surface temperature", "surface temperature", "LST"]),
    (("t2m", "tair", "air_temp", "tavg"), ["air temperature", "surface air temperature", "temperature", "warming"]),
    (("precip", "prcp", "rain"), ["precipitation", "rainfall"]),
    (("soilmoist", "soil_moisture"), ["soil moisture"]),
    (("evap", "_et"), ["evapotranspiration", "evaporation"]),
    (("runoff", "streamflow", "discharge", "flow"), ["streamflow", "runoff", "river discharge"]),
    (("swe", "snow"), ["snow water equivalent", "snow cover", "snowpack", "snow"]),
    (("groundwater", "grace", "tws"), ["groundwater", "terrestrial water storage", "GRACE"]),
    (("no2",), ["NO2", "nitrogen dioxide"]),
    (("aerosol", "aod"), ["aerosol optical depth", "aerosol index", "aerosol"]),
    (("ozone",), ["total column ozone", "ozone"]),
    (("qv2m", "humidity"), ["specific humidity", "humidity", "water vapor"]),
    (("sst", "sea_surface"), ["sea surface temperature", "SST"]),
    (("seaice", "sea_ice"), ["sea ice extent", "sea ice"]),
    (("chlor",), ["chlorophyll-a", "chlorophyll"]),
    (("sea_level", "tide", "water_level", "lake", "swot"), ["water level", "sea level", "lake level"]),
    (("xco2", "co2"), ["carbon dioxide", "CO2"]),
]
TREND = re.compile(r"\b(trend\w*|increas\w*|decreas\w*|declin\w*|change\w*|long-term|interannual|decad\w*)\b", re.I)
# "higher/lower/gain/loss/enhanced/reduced" are left out on purpose: in abstracts they mostly compare
# products or errors ("TROPOMI higher than OMI", "lower error"), not a change over time
UP = re.compile(r"\b(increas\w*|ris(?:e|es|ing|en)|rose|greening|wetter|wetting|warming|warmer|upward|"
                r"intensif\w*|positive trend\w*|expan(?:d|ded|ding|sion))\b", re.I)
DOWN = re.compile(r"\b(decreas\w*|declin\w*|drying|drier|browning|cooling|cooler|downward|negative trend\w*|"
                  r"deplet\w*|shrink\w*|fell|fallen|drop\w*|thinn\w*|retreat\w*|melt\w*|record low\w*|"
                  r"all-time low)\b", re.I)
NEGATED = re.compile(r"\b(not|no longer|never|did not|does not|do not|didn't|doesn't|neither|nor|without|"
                     r"rather than|instead of)\b", re.I)
FLAT = re.compile(r"\b(no (?:significant )?(?:trend|change)|not significant|insignificant|non-significant|"
                  r"no clear trend|stable|unchanged)\b", re.I)
SENT = re.compile(r"(?<=[.!?])\s+")
DIRS = ("rising", "falling", "no_trend", "mixed", "unclear")


def terms_for(variable_id: str, name: str | None) -> list[str]:
    vid = (variable_id or "").lower()
    for keys, terms in TERMS:
        if any(k in vid for k in keys):
            return terms
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", name or variable_id or "")
             if w.lower() not in ("the", "and", "from", "with", "model", "satellite", "monthly", "nasa", "noaa")]
    return [" ".join(words[:3])] + words[:4] if words else [name or variable_id]


def _has(text: str, terms: list[str]) -> bool:
    t = text.lower()
    return any(term.lower() in t for term in terms)


def trust(p: dict) -> tuple[float, str]:
    """How much a paper counts as evidence: peer-reviewed journal > NASA report > other > preprint."""
    if p.get("peer_reviewed"):
        return 1.0, "peer-reviewed journal"
    if p.get("source") == "NASA NTRS":
        return 0.85, "NASA technical report"
    if p.get("source") == "arXiv" or "preprint" in (p.get("venue") or "").lower() or "egusphere" in (p.get("doi") or ""):
        return 0.6, "preprint (not peer-reviewed)"
    return 0.75, "other publication"


def relevance(p: dict, terms: list[str], region: str | None, today_year: int) -> float:
    title, abstract = p.get("title") or "", p.get("abstract") or ""
    text = f"{title} {abstract}"
    s = 0.0
    s += 2.0 if _has(title, terms) else (1.0 if _has(abstract, terms) else 0.0)
    if region:
        s += 2.0 if region.lower() in text.lower() else 0.0
    s += 1.0 if TREND.search(text) else 0.0
    age = max(0, today_year - int(p.get("year") or today_year))
    return s * math.exp(-0.07 * age) * trust(p)[0]


def read_stance(abstract: str, terms: list[str]) -> dict:
    """Deterministic: only sentences that name the variable count."""
    up = down = flat = 0
    best = None
    for sent in SENT.split(abstract or ""):
        if not _has(sent, terms) or sent.rstrip().endswith("?") or NEGATED.search(sent):
            continue                       # negated or question sentences are not evidence of a direction
        f, u, d = bool(FLAT.search(sent)), len(UP.findall(sent)), len(DOWN.findall(sent))
        if f:
            flat += 1
        elif u > d:
            up += 1
        elif d > u:
            down += 1
        else:
            continue
        best = best or sent
    if up and not down:
        st = "rising"
    elif down and not up:
        st = "falling"
    elif up and down:
        st = "mixed"
    elif flat:
        st = "no_trend"
    else:
        st = "unclear"
    return {"stance": st, "evidence_quote": best, "read_by": "lexicon"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def verify_ai_reading(abstract: str, reading: dict) -> tuple[bool, str]:
    """Accept an AI reading only if its quote is verbatim in the abstract and supports the stance."""
    q = reading.get("evidence_quote") or ""
    st = reading.get("stance")
    if st not in DIRS:
        return False, "unknown stance"
    if len(q) < 20 or _norm(q) not in _norm(abstract):
        return False, "quote is not in the abstract"
    if st in ("rising", "falling") and NEGATED.search(q):
        return False, "quote is negated"
    if st == "mixed" and not (UP.search(q) and DOWN.search(q)):
        return False, "quote does not describe both directions"
    if st == "rising" and not UP.search(q):
        return False, "quote does not describe an increase"
    if st == "falling" and not DOWN.search(q):
        return False, "quote does not describe a decrease"
    if st == "no_trend" and not FLAT.search(q):
        return False, "quote does not describe 'no trend'"
    return True, "verified"


READ_SCHEMA = {"type": "object", "properties": {
    "stance": {"type": "string", "enum": list(DIRS)},
    "region_matches": {"type": "boolean"},
    "evidence_quote": {"type": "string"}},
    "required": ["stance", "region_matches", "evidence_quote"]}


async def ai_read(llm, p: dict, variable_name: str, region: str | None) -> dict | None:
    if llm is None:
        return None
    msgs = [{"role": "system", "content": "You read one scientific abstract. Report what it says about the trend "
             "(direction over time) of the named variable. Copy ONE sentence from the abstract word for word as "
             "evidence_quote. If the abstract does not report a trend for this variable, use 'unclear'."},
            {"role": "user", "content": f"VARIABLE: {variable_name}\nREGION OF INTEREST: {region or 'any'}\n"
             f"TITLE: {p['title']}\nABSTRACT: {p['abstract'][:3000]}"}]
    return await llm.chat_json(msgs, READ_SCHEMA, max_tokens=250)


def agreement(data_direction: str, papers: list[dict]) -> dict:
    sup = con = neu = 0.0
    n_sup = n_con = 0
    for p in papers:
        w = p["relevance"] * (1.0 if p.get("region_match") else 0.5)
        st = p["stance"]
        if st == data_direction:
            sup += w
            n_sup += 1
        elif st in ("rising", "falling"):
            con += w
            n_con += 1
        elif st == "no_trend":
            neu += w
    if not (n_sup or n_con):
        label = "no_literature" if not papers else "inconclusive"
    elif sup >= 2 * con:
        label = "supported"
    elif con >= 2 * sup:
        label = "conflicts"
    else:
        label = "mixed"
    score = sup / (sup + con) if sup + con > 0 else None
    return {"label": label, "support_weight": sup, "conflict_weight": con, "no_trend_weight": neu,
            "n_supporting": n_sup, "n_conflicting": n_con, "score": score}


async def research_evidence(http, llm, *, variable_id: str, variable_name: str | None, region_name: str | None,
                            direction: str, max_age_years: int = 10, per_source: int = 15, springer_key: str = "",
                            semantic_key: str = "", ads_token: str = "",
                            ai_reads: int = 5, min_relevance: float = 2.5) -> dict:
    today = date.today().year
    since = today - max_age_years
    terms = terms_for(variable_id, variable_name)
    region = (region_name or "").strip() or None
    query = " ".join(filter(None, [terms[0], region, "trend"]))
    papers, sources = await literature.search(http, query=query, terms=[terms[0], *([region] if region else [])],
                                              since_year=since, per_source=per_source, springer_key=springer_key,
                                              semantic_key=semantic_key, ads_token=ads_token)
    for p in papers:
        p["relevance"] = relevance(p, terms, region, today)
        p["trust"] = trust(p)[1]
        p["region_match"] = bool(region and region.lower() in f"{p['title']} {p['abstract']}".lower())
    papers = sorted([p for p in papers if p["relevance"] >= min_relevance], key=lambda p: -p["relevance"])[:12]

    n_ai_ok = n_ai_rejected = 0
    for i, p in enumerate(papers):
        p.update(read_stance(p["abstract"], terms))
        if i < ai_reads:
            r = await ai_read(llm, p, variable_name or terms[0], region)
            if r:
                ok, why = verify_ai_reading(p["abstract"], r)
                if ok:
                    p.update(stance=r["stance"], evidence_quote=r["evidence_quote"], read_by="local AI (quote verified)")
                    n_ai_ok += 1
                else:
                    p["ai_reading_rejected"] = why
                    n_ai_rejected += 1
    ag = agreement(direction, papers)
    shown = [{k: p.get(k) for k in ("title", "year", "venue", "authors", "doi", "url", "source", "peer_reviewed",
                                    "trust", "stance", "evidence_quote", "read_by", "ai_reading_rejected", "region_match",
                                    "relevance")} for p in papers[:8]]
    return {
        "query": query, "since_year": since, "sources": sources,
        "n_relevant": len(papers), "papers": shown, "agreement": ag,
        "ai_readings": {"accepted": n_ai_ok, "rejected_as_unsupported": n_ai_rejected},
        "plain_language": ("The literature sources could not be reached, so no research comparison was made."
                           if not any(s["status"] == "ok" for s in sources) else
                           _plain(ag, papers, direction, variable_name or terms[0], region, since)),
        "limits": ["Papers are matched by keywords and read from abstracts only.",
                   "Research agreement is context: it cannot turn data that failed verification into a trend.",
                   "Studies may use other datasets, periods or region boundaries than this analysis."],
    }


def _cite(p: dict) -> str:
    a = (p.get("authors") or ["?"])[0] or "?"
    last = a.split()[-1] if a and a != "?" else "Unknown"
    return f"{last} et al. {p.get('year')}" + (f" (doi:{p['doi']})" if p.get("doi") else "")


def _plain(ag: dict, papers: list[dict], direction: str, var: str, region: str | None, since: int) -> str:
    where = f" for {region}" if region else ""
    if ag["label"] == "no_literature":
        return f"No recent ({since}+) studies on {var}{where} were found in the searched literature sources."
    sup = [p for p in papers if p["stance"] == direction][:3]
    con = [p for p in papers if p["stance"] in ("rising", "falling") and p["stance"] != direction][:2]
    if ag["label"] == "supported":
        return (f"Recent research agrees: {ag['n_supporting']} relevant studies since {since} also report {var} "
                f"{direction}{where} (e.g. {'; '.join(_cite(p) for p in sup)}).")
    if ag["label"] == "conflicts":
        return (f"Caution: {ag['n_conflicting']} relevant studies report the opposite direction for {var}{where} "
                f"(e.g. {'; '.join(_cite(p) for p in con)}). Check periods and datasets before trusting this trend.")
    if ag["label"] == "mixed":
        return (f"Research is mixed: {ag['n_supporting']} studies agree and {ag['n_conflicting']} disagree on the "
                f"direction of {var}{where}.")
    return f"Studies on {var}{where} were found, but their abstracts do not state a clear direction."


LABEL_W = {"VERIFIED": 1.0, "PROBABLE": 0.6, "NOT VERIFIED": 0.0}
LIT_W = {"supported": 1.0, "mixed": 0.5, "inconclusive": 0.3, "no_literature": 0.3, "conflicts": 0.0}


def choose_best(trends: list[dict]) -> dict:
    """Rank active trends: data verdict 60%, size of change 20%, research agreement 20%."""
    ranked = []
    for tr in trends:
        lab = tr["verdict"]["label"]
        if lab == "NOT VERIFIED":
            continue
        eff = abs(tr["detect"].get("effect_sd_per_decade") or 0.0)
        lit = (tr.get("research") or {}).get("agreement", {}).get("label", "no_literature")
        score = 0.6 * LABEL_W[lab] + 0.2 * min(1.0, eff) + 0.2 * LIT_W.get(lit, 0.3)
        ranked.append({"variable_id": tr["variable_id"], "name": tr["name"], "label": lab, "research": lit,
                       "effect_sd_per_decade": eff, "score": round(score, 3)})
    ranked.sort(key=lambda r: -r["score"])
    if not ranked:
        return {"best": None, "ranking": [],
                "plain_language": "No trend passed verification, so none is recommended."}
    b = ranked[0]
    tr = next(t for t in trends if t["variable_id"] == b["variable_id"])
    why = [f"{b['label']} by the data checks ({tr['verdict']['why']})"]
    rp = (tr.get("research") or {}).get("plain_language")
    if rp:
        why.append(rp)
    return {"best": b, "ranking": ranked, "explanation": tr["detect"].get("plain_language"),
            "plain_language": f"Best-supported trend: {b['name']}. " + " ".join(why),
            "scoring": "0.6 x data verdict (VERIFIED=1, PROBABLE=0.6) + 0.2 x size of change (SD/decade, capped at 1) "
                       "+ 0.2 x research agreement (supported=1, mixed=0.5, none=0.3, conflicts=0)"}
