"""Live literature search for the Research Evidence step.

Official, documented APIs only (no scraping):
  * arXiv API          https://info.arxiv.org/help/api/  (Atom feed, no key)
  * OpenAlex API       https://docs.openalex.org/        (open index of ~250M works; covers the papers
                       Google Scholar indexes. Google Scholar itself has no API and forbids scraping.)
  * Springer Nature    https://dev.springernature.com/   (Meta API v2; needs a free key: SPRINGER_API_KEY)
  * Crossref           https://api.crossref.org          (every DOI-registered article; no key)
  * Semantic Scholar   https://api.semanticscholar.org   (no key = shared, often rate-limited pool;
                       free key SEMANTIC_SCHOLAR_API_KEY recommended)
  * NASA NTRS          https://ntrs.nasa.gov/api         (NASA Technical Reports Server; no key)
  * NASA ADS           https://ui.adsabs.harvard.edu     (NASA-funded Astrophysics Data System, incl. Earth
                       science; free token ADS_API_TOKEN)
Default (always on, no key, reliable): arXiv, OpenAlex, Crossref, NASA NTRS. Keyed sources are used
only when their key/token is set. Retracted works are excluded (OpenAlex is_retracted filter).
Google Scholar is NOT used: it has no API, its terms forbid automated scraping and it answers bots with
CAPTCHAs. OpenAlex + Crossref + Semantic Scholar cover the same journal literature through official APIs.

Every source is optional: a failing or unconfigured source is reported in `sources` and skipped.
Responses go through ResilientHTTP, so they are cached and rate-limit friendly.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

ARXIV = "https://export.arxiv.org/api/query"
OPENALEX = "https://api.openalex.org/works"
SPRINGER = "https://api.springernature.com/meta/v2/json"
CROSSREF = "https://api.crossref.org/works"
SEMANTIC = "https://api.semanticscholar.org/graph/v1/paper/search"
NTRS = "https://ntrs.nasa.gov/api/citations/search"
ADS = "https://api.adsabs.harvard.edu/v1/search/query"
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
        "filter": f"from_publication_date:{since_year}-01-01,has_abstract:true,is_retracted:false",
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


async def crossref(http, query: str, since_year: int, n: int) -> list[dict]:
    r = await http.request("GET", CROSSREF, params={
        "query.bibliographic": query, "rows": n,
        "filter": f"from-pub-date:{since_year}-01-01,has-abstract:true",
        "select": "DOI,title,abstract,issued,container-title,author,type"})
    out = []
    for w in r.json().get("message", {}).get("items", []):
        y = ((w.get("issued") or {}).get("date-parts") or [[0]])[0][0] or 0
        out.append({"source": "Crossref", "title": _clean((w.get("title") or [""])[0]),
                    "abstract": _clean(w.get("abstract")), "year": y, "doi": w.get("DOI"),
                    "url": f"https://doi.org/{w['DOI']}" if w.get("DOI") else None,
                    "venue": (w.get("container-title") or [None])[0],
                    "authors": [" ".join(filter(None, [a.get("given"), a.get("family")])) for a in (w.get("author") or [])][:3],
                    "peer_reviewed": w.get("type") == "journal-article"})
    return out


async def semantic_scholar(http, query: str, since_year: int, n: int, api_key: str = "") -> list[dict]:
    r = await http.request("GET", SEMANTIC, params={
        "query": query, "limit": n, "year": f"{since_year}-",
        "fields": "title,abstract,year,externalIds,venue,authors,publicationTypes,url"},
        headers={"x-api-key": api_key} if api_key else None)
    out = []
    for w in r.json().get("data", []) or []:
        doi = (w.get("externalIds") or {}).get("DOI")
        out.append({"source": "Semantic Scholar", "title": _clean(w.get("title")), "abstract": _clean(w.get("abstract")),
                    "year": w.get("year") or 0, "doi": doi, "url": f"https://doi.org/{doi}" if doi else w.get("url"),
                    "venue": w.get("venue"), "authors": [a.get("name") for a in (w.get("authors") or [])][:3],
                    "peer_reviewed": "JournalArticle" in (w.get("publicationTypes") or [])})
    return out


async def ntrs(http, query: str, since_year: int, n: int) -> list[dict]:
    r = await http.request("GET", NTRS, params={"q": query, "page.size": n})
    out = []
    for w in r.json().get("results", []):
        pubs = w.get("publications") or [{}]
        y = int(str(pubs[0].get("publicationDate") or w.get("submittedDate") or "0")[:4] or 0)
        if y < since_year:
            continue
        out.append({"source": "NASA NTRS", "title": _clean(w.get("title")), "abstract": _clean(w.get("abstract")),
                    "year": y, "doi": pubs[0].get("doi"), "url": f"https://ntrs.nasa.gov/citations/{w.get('id')}",
                    "venue": pubs[0].get("publicationName") or "NASA Technical Reports Server",
                    "authors": [((a.get("meta") or {}).get("author") or {}).get("name")
                                for a in (w.get("authorAffiliations") or [])][:3],
                    "peer_reviewed": False})
    return out


async def nasa_ads(http, query: str, since_year: int, n: int, token: str) -> list[dict]:
    r = await http.request("GET", ADS, params={"q": f"{query} year:{since_year}-", "rows": n,
                                               "fl": "title,abstract,year,doi,pub,author,doctype,bibcode"},
                           headers={"Authorization": f"Bearer {token}"})
    out = []
    for w in r.json().get("response", {}).get("docs", []):
        doi = (w.get("doi") or [None])[0]
        out.append({"source": "NASA ADS", "title": _clean((w.get("title") or [""])[0]), "abstract": _clean(w.get("abstract")),
                    "year": int(w.get("year") or 0), "doi": doi,
                    "url": f"https://doi.org/{doi}" if doi else f"https://ui.adsabs.harvard.edu/abs/{w.get('bibcode')}",
                    "venue": w.get("pub"), "authors": (w.get("author") or [])[:3],
                    "peer_reviewed": w.get("doctype") == "article"})
    return out


def _key(p: dict) -> str:
    """Title first: a preprint and its journal version have different DOIs but the same title."""
    t = re.sub(r"[^a-z0-9]", "", (p.get("title") or "").lower())[:80]
    return t if len(t) >= 20 else (p.get("doi") or "").lower() or t


async def search(http, *, query: str, terms: list[str], since_year: int, per_source: int = 15,
                 springer_key: str = "", semantic_key: str = "", ads_token: str = "",
                 timeout: float = 25.0) -> tuple[list[dict], list[dict]]:
    """Returns (papers deduplicated by DOI/title, per-source status)."""
    import asyncio
    calls = {"arXiv": arxiv(http, terms, since_year, per_source),
             "OpenAlex": openalex(http, query, since_year, per_source),
             "Crossref": crossref(http, query, since_year, per_source),
             "NASA NTRS": ntrs(http, query, since_year, per_source)}
    # keyed sources are used only when configured (keyless Semantic Scholar is usually rate-limited)
    if semantic_key:
        calls["Semantic Scholar"] = semantic_scholar(http, query, since_year, per_source, semantic_key)
    if springer_key:
        calls["Springer Nature"] = springer(http, query, since_year, per_source, springer_key)
    if ads_token:
        calls["NASA ADS"] = nasa_ads(http, query, since_year, per_source, ads_token)
    # a rate-limited source (e.g. keyless Semantic Scholar answering 429) must not stall the scan
    results = await asyncio.gather(*(asyncio.wait_for(c, timeout) for c in calls.values()), return_exceptions=True)
    papers, seen, sources = [], set(), []
    for name, res in zip(calls, results):
        if isinstance(res, Exception):
            sources.append({"source": name, "status": "unavailable", "reason": type(res).__name__})
            continue
        sources.append({"source": name, "status": "ok", "n": len(res)})
        for p in res:
            k = _key(p)
            if not k or not p.get("abstract"):
                continue
            if k in seen:                  # keep the peer-reviewed copy of a duplicate
                i = next(j for j, q in enumerate(papers) if _key(q) == k)
                if p.get("peer_reviewed") and not papers[i].get("peer_reviewed"):
                    papers[i] = p
                continue
            seen.add(k)
            papers.append(p)
    if not springer_key:
        sources.append({"source": "Springer Nature", "status": "not_configured",
                        "reason": "set SPRINGER_API_KEY (free) to include Springer journals"})
    if not semantic_key:
        sources.append({"source": "Semantic Scholar", "status": "not_configured",
                        "reason": "set SEMANTIC_SCHOLAR_API_KEY (free) to include Semantic Scholar"})
    if not ads_token:
        sources.append({"source": "NASA ADS", "status": "not_configured",
                        "reason": "set ADS_API_TOKEN (free) to include NASA ADS"})
    return papers, sources
