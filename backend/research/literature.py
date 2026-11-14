"""Live literature search for the Research Evidence step.

Official, documented APIs only (no scraping):
  * arXiv API          https://info.arxiv.org/help/api/  (Atom feed, no key)
  * OpenAlex API       https://docs.openalex.org/        (open index of ~250M works; covers the papers
                       Google Scholar indexes. Google Scholar itself has no API and forbids scraping.)
  * Springer Nature    https://dev.springernature.com/   (Meta API v2; needs a free key: SPRINGER_API_KEY)

Every source is optional: a failing or unconfigured source is reported in `sources` and skipped.
Responses go through ResilientHTTP, so they are cached and rate-limit friendly.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

ARXIV = "https://export.arxiv.org/api/query"
OPENALEX = "https://api.openalex.org/works"
SPRINGER = "https://api.springernature.com/meta/v2/json"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


async def arxiv(http, terms: list[str], since_year: int, n: int) -> list[dict]:
    q = " AND ".join(f'all:"{t}"' if " " in t else f"all:{t}" for t in terms)
    r = await http.request("GET", ARXIV, params={"search_query": q, "start": 0, "max_results": n,
                                                 "sortBy": "relevance", "sortOrder": "descending"})
    root = ET.fromstring(r.text)
    out = []
    for e in root.findall("a:entry", ATOM):
        year = int((e.findtext("a:published", "", ATOM) or "0000")[:4] or 0)
        if year < since_year:
            continue
        doi = e.findtext("arxiv:doi", None, ATOM)
        out.append({"source": "arXiv", "title": _clean(e.findtext("a:title", "", ATOM)),
                    "abstract": _clean(e.findtext("a:summary", "", ATOM)), "year": year, "doi": doi,
                    "url": e.findtext("a:id", "", ATOM), "venue": "arXiv preprint",
                    "authors": [_clean(a.findtext("a:name", "", ATOM)) for a in e.findall("a:author", ATOM)][:3],
                    "peer_reviewed": False})
    return out


async def openalex(http, query: str, since_year: int, n: int) -> list[dict]:
    r = await http.request("GET", OPENALEX, params={
        "search": query, "per-page": n,
        "filter": f"from_publication_date:{since_year}-01-01,has_abstract:true",
        "select": "id,doi,title,publication_year,abstract_inverted_index,primary_location,authorships,type"})
    out = []
    for w in r.json().get("results", []):
        loc = (w.get("primary_location") or {}).get("source") or {}
        out.append({"source": "OpenAlex", "title": _clean(w.get("title")),
                    "abstract": _clean(_openalex_abstract(w.get("abstract_inverted_index"))),
                    "year": w.get("publication_year"), "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                    "url": w.get("doi") or w.get("id"), "venue": loc.get("display_name"),
                    "authors": [(a.get("author") or {}).get("display_name") for a in (w.get("authorships") or [])][:3],
                    "peer_reviewed": w.get("type") == "article" and loc.get("type") == "journal"})
    return out


def _springer_abstract(a) -> str:
    if isinstance(a, str):
        return _clean(a)
    if isinstance(a, dict):
        return _clean(" ".join(str(v) if not isinstance(v, list) else " ".join(map(str, v)) for v in a.values()))
    if isinstance(a, list):
        return _clean(" ".join(_springer_abstract(x) for x in a))
    return ""


async def springer(http, query: str, since_year: int, n: int, api_key: str) -> list[dict]:
    r = await http.request("GET", SPRINGER, params={"q": f"{query} onlinedatefrom:{since_year}-01-01",
                                                    "p": n, "api_key": api_key})
    out = []
    for rec in r.json().get("records", []):
        urls = rec.get("url") or []
        out.append({"source": "Springer Nature", "title": _clean(rec.get("title")),
                    "abstract": _springer_abstract(rec.get("abstract")),
                    "year": int(str(rec.get("publicationDate") or "0")[:4] or 0), "doi": rec.get("doi"),
                    "url": (urls[0].get("value") if urls and isinstance(urls[0], dict) else None)
                           or (f"https://doi.org/{rec['doi']}" if rec.get("doi") else None),
                    "venue": rec.get("publicationName"),
                    "authors": [c.get("creator") for c in (rec.get("creators") or [])][:3], "peer_reviewed": True})
    return out


def _key(p: dict) -> str:
    return (p.get("doi") or "").lower() or re.sub(r"[^a-z0-9]", "", (p.get("title") or "").lower())[:80]


async def search(http, *, query: str, terms: list[str], since_year: int, per_source: int = 15,
                 springer_key: str = "") -> tuple[list[dict], list[dict]]:
    """Returns (papers deduplicated by DOI/title, per-source status)."""
    import asyncio
    calls = {"arXiv": arxiv(http, terms, since_year, per_source),
             "OpenAlex": openalex(http, query, since_year, per_source)}
    if springer_key:
        calls["Springer Nature"] = springer(http, query, since_year, per_source, springer_key)
    results = await asyncio.gather(*calls.values(), return_exceptions=True)
    papers, seen, sources = [], set(), []
    for name, res in zip(calls, results):
        if isinstance(res, Exception):
            sources.append({"source": name, "status": "unavailable", "reason": type(res).__name__})
            continue
        sources.append({"source": name, "status": "ok", "n": len(res)})
        for p in res:
            k = _key(p)
            if k and k not in seen and p.get("abstract"):
                seen.add(k)
                papers.append(p)
    if not springer_key:
        sources.append({"source": "Springer Nature", "status": "not_configured",
                        "reason": "set SPRINGER_API_KEY (free) to include Springer journals"})
    return papers, sources
