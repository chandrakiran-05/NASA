"""Stage 3 extras: preprints (not peer reviewed) and recent news (not peer reviewed).

Peer-reviewed literature comes from research.evidence.research_evidence (arXiv, OpenAlex, Crossref, NTRS,
optional Springer / Semantic Scholar / ADS). This module adds two clearly separated, unreviewed streams:
  preprints  OpenAlex works with type:preprint, plus arXiv
  news       GDELT DOC 2.0 article list (keyless), last few months
Every source runs with a timeout; a failing source is listed with its reason and never stops the job.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from ..research import literature
from ..research.evidence import read_stance, terms_for

OPENALEX = "https://api.openalex.org/works"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
SOURCE_TIMEOUT_S = 20.0
GDELT_MIN_INTERVAL_S = 5.5          # GDELT asks clients for at most one request every 5 seconds
GDELT_TIMEOUT_S = 45.0              # GDELT often takes 10-20 s to answer
# news wording differs from paper wording: plain keywords per criterion (GDELT OR-groups need parentheses)
NEWS_WORDS = {
    "temperature": "(heatwave OR temperature)", "atmospheric_temperature": "(heatwave OR temperature)",
    "precipitation": "(rainfall OR monsoon OR drought OR flood)", "soil_moisture": "(drought OR \"soil moisture\")",
    "sea_surface_temperature": "(\"sea surface temperature\" OR \"marine heatwave\")",
    "vegetation": "(vegetation OR greening OR deforestation)", "forest_condition": "(forest OR deforestation)",
    "snow_ice": "(snow OR glacier)", "sea_ice": "\"sea ice\"",
    "atmospheric_composition": "(\"air quality\" OR pollution OR smog)", "chlorophyll": "(\"algal bloom\" OR chlorophyll)",
}
PREPRINT_LABEL = "preprint: not peer reviewed"
NEWS_LABEL = "news report: not peer reviewed"
_gdelt_lock = asyncio.Lock()
_gdelt_last = [0.0]


def _q(s: str) -> str:
    return f'"{s}"' if " " in s else s


async def openalex_preprints(http, query: str, since_year: int, n: int) -> list[dict]:
    r = await http.request("GET", OPENALEX, params={
        "search": query, "per-page": n,
        "filter": f"type:preprint,from_publication_date:{since_year}-01-01,is_retracted:false",
        "select": "id,doi,title,publication_year,abstract_inverted_index,primary_location,authorships,publication_date"})
    out = []
    for w in r.json().get("results", []):
        loc = (w.get("primary_location") or {}).get("source") or {}
        out.append({"source": "OpenAlex (preprint)", "title": literature._clean(w.get("title")),
                    "abstract": literature._clean(literature._openalex_abstract(w.get("abstract_inverted_index"))),
                    "year": w.get("publication_year"), "date": w.get("publication_date"),
                    "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                    "url": w.get("doi") or w.get("id"), "venue": loc.get("display_name"),
                    "authors": [(a.get("author") or {}).get("display_name") for a in (w.get("authorships") or [])][:3]})
    return out


async def preprints(http, *, variable_id: str, variable_name: str | None, place: str | None, since_year: int,
                    direction: str | None = None, n: int = 10) -> dict:
    terms = terms_for(variable_id, variable_name)
    query = " ".join(filter(None, [terms[0], place, "trend"]))
    calls = {"OpenAlex preprints": openalex_preprints(http, query, since_year, n),
             "arXiv": literature.arxiv(http, [terms[0], *([place] if place else [])], since_year, n)}
    res = await asyncio.gather(*(asyncio.wait_for(c, SOURCE_TIMEOUT_S) for c in calls.values()), return_exceptions=True)
    sources, items, seen = [], [], set()
    for name, r in zip(calls, res):
        if isinstance(r, BaseException):
            sources.append({"source": name, "status": "unavailable", "reason": type(r).__name__})
            continue
        sources.append({"source": name, "status": "ok", "n": len(r)})
        for p in r:
            text = f"{p.get('title') or ''} {p.get('abstract') or ''}".lower()
            if not any(t.lower() in text for t in terms):
                continue
            if place and place.lower() not in text:
                continue
            key = literature._key(p)
            if not key or key in seen:
                continue
            seen.add(key)
            stance = read_stance(p.get("abstract") or "", terms).get("stance") if p.get("abstract") else "unclear"
            items.append({"title": p.get("title"), "year": p.get("year"), "date": p.get("date"),
                          "doi": p.get("doi"), "url": p.get("url"), "source": p.get("source"),
                          "authors": p.get("authors"), "stance": stance, "peer_reviewed": False,
                          "label": PREPRINT_LABEL})
    ok = any(s["status"] == "ok" for s in sources)
    return {"status": "ok" if ok else "unavailable", "query": query, "sources": sources, "items": items[:6],
            "n_same_direction": sum(i["stance"] == direction for i in items) if direction else None,
            "label": PREPRINT_LABEL}


def _gdelt_date(s: str | None) -> str | None:
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d") if s else None
    except ValueError:
        return None


async def _gdelt_call(http, params: dict):
    async with _gdelt_lock:                          # politeness: one request every few seconds
        wait = GDELT_MIN_INTERVAL_S - (time.monotonic() - _gdelt_last[0])
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await http.request("GET", GDELT, params=params)
        finally:
            _gdelt_last[0] = time.monotonic()


async def news(http, *, variable_id: str, variable_name: str | None, place: str | None, criterion: str | None = None,
               timespan: str = "3m", n: int = 8) -> dict:
    """Recent news headlines from GDELT (keyless). Headlines are context only, never evidence."""
    words = NEWS_WORDS.get(criterion or "") or _q(terms_for(variable_id, variable_name)[0])
    query = " ".join(filter(None, [words, _q(place) if place else None, "sourcelang:english"]))
    params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": n, "timespan": timespan,
              "sort": "datedesc"}
    try:
        r = await asyncio.wait_for(_gdelt_call(http, params), GDELT_TIMEOUT_S + GDELT_MIN_INTERVAL_S)
        try:
            data = r.json()
        except ValueError:                           # GDELT answers plain text for rejected queries
            return {"status": "unavailable", "query": query, "items": [], "label": NEWS_LABEL,
                    "sources": [{"source": "GDELT", "status": "unavailable",
                                 "reason": (r.text or "not JSON")[:160].strip()}]}
    except Exception as exc:  # noqa: BLE001 - news is optional context
        return {"status": "unavailable", "query": query, "items": [], "label": NEWS_LABEL,
                "sources": [{"source": "GDELT", "status": "unavailable", "reason": type(exc).__name__}]}
    items = [{"title": a.get("title"), "url": a.get("url"), "domain": a.get("domain"),
              "date": _gdelt_date(a.get("seendate")), "country": a.get("sourcecountry"), "label": NEWS_LABEL}
             for a in (data.get("articles") or []) if a.get("url") and a.get("title")]
    return {"status": "ok", "query": query, "timespan": timespan, "items": items[:n], "label": NEWS_LABEL,
            "sources": [{"source": "GDELT", "status": "ok", "n": len(items)}]}
