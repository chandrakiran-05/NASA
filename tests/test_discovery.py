"""Discovery mode: gap flag, honest wording, brief structure, notebook JSON, failing sources, API job."""
import asyncio
import json
import re
from datetime import date

import httpx
import numpy as np
import pandas as pd
import pytest

from backend.core.config import Settings
from backend.core.geometry import Region
from backend.core.http import ResilientHTTP
from backend.discovery import brief as B
from backend.discovery import sources
from backend.discovery.notebook import build_notebook
from backend.discovery.sweep import literature_place, pick_cells, place_name
from backend.timeseries.model import MonthlySeries, Provenance
from tests.conftest import wait_job

N = 25 * 12
T = np.arange(N) / 12
IDX = pd.date_range("2000-01-01", periods=N, freq="MS")
YEAR = date.today().year


def series(slope=0.05, seed=1) -> MonthlySeries:
    rng = np.random.default_rng(seed)
    e = np.zeros(N)
    z = rng.normal(0, 0.4, N)
    for i in range(1, N):
        e[i] = 0.3 * e[i - 1] + z[i]
    return MonthlySeries(time=IDX, value=slope * T + 4 * np.sin(2 * np.pi * T) + e, units="°C",
                         provenance=Provenance(source_api="user", variable="v", geometry={}), variable_id="merra2_t2m")


def research(papers, ok=True):
    return {"query": "q", "sources": [{"source": "OpenAlex", "status": "ok" if ok else "unavailable"}],
            "papers": papers, "agreement": {"label": "no_literature"}, "plain_language": "p", "limits": []}


PAPER = {"title": "Air temperature trend", "year": YEAR, "doi": "10.1/x", "url": "https://doi.org/10.1/x",
         "peer_reviewed": True, "region_match": False, "stance": "rising", "source": "OpenAlex"}


# ------------------------------------------------------------------ gap flag
def test_gap_flag_rules():
    g = B.gap_flag(research([PAPER]), "Sahel")
    assert g["potential_discovery"] is True and g["label"] == B.POTENTIAL_LABEL
    assert "not yet checked by scientists" in g["label"]
    assert B.gap_flag(research([{**PAPER, "region_match": True}]), "Sahel")["potential_discovery"] is False
    # a preprint naming the place does not count as a published study
    assert B.gap_flag(research([{**PAPER, "region_match": True, "peer_reviewed": False}]), "Sahel")["potential_discovery"]
    # no answer from the literature, or no usable place name -> no flag at all (never a guess)
    assert B.gap_flag(research([], ok=False), "Sahel")["potential_discovery"] is None
    assert B.gap_flag({"status": "unavailable"}, "Sahel")["potential_discovery"] is None
    assert B.gap_flag(research([]), None)["potential_discovery"] is None


def test_sweep_helpers():
    cells = [{"lat": 10, "lon": 10, "p": 0.001, "slope_per_decade": 0.3}, {"lat": 11, "lon": 11, "p": 0.0005,
             "slope_per_decade": 0.2}, {"lat": 40, "lon": 10, "p": 0.01, "slope_per_decade": -0.5}]
    picked = pick_cells(cells, 3)
    assert [c["lat"] for c in picked] == [11, 40]                  # neighbours of a stronger cell are dropped
    assert literature_place("Amazon Basin (near 3.0°S, 60.0°W)") == "Amazon"
    assert literature_place("Bay of Bengal (near 15.0°N, 88.0°E)") == "Bay of Bengal"
    assert literature_place("grid box at 1.0°N, 2.0°E") is None
    assert place_name(88.0, 15.0, ocean=True).startswith("Bay of Bengal")


# ------------------------------------------------------------------ a brief built from engine-shaped inputs
def _brief(gap_papers=(PAPER,), pre=None, nw=None):
    ms = series()
    det = {"direction": "rising", "rate_per_decade": 0.52, "units": "°C", "plain_language": "Rising now: +0.52 °C per decade.",
           "recent_window": {"start": "2015-01", "end": "2024-12"}, "recent": {"ci95_per_decade": [0.3, 0.7]}}
    verdict = {"label": "VERIFIED", "why": "passed 5 of 5 checks and BEAST agrees", "limit": "VERIFIED means ...",
               "plain_language": "VERIFIED: rising", "test_note": "t", "data_note": "d"}
    beast = {"status": "agrees", "plain_language": "BEAST agrees", "active_since": {"date": "2012-05",
             "interval90": ["2011-01", "2013-01"], "probability": 0.9}}
    view = {"units": "°C", "chart": {"time": [str(t.date()) for t in IDX], "observed": list(ms.value),
                                     "deseasonalized": list(ms.value), "sen_line": list(ms.value), "beast_trend": None},
            "markers": [{"date": "2012-05", "kind": "beast_confirmed"}]}
    trend = {"variable_id": "merra2_t2m", "name": "Air temperature", "series_id": "s_1", "detect": det,
             "verdict": verdict, "beast": beast, "view": view,
             "checks": [{"check": "court", "status": "pass", "plain_language": "ok"}]}
    cand = {"id": "c1", "region": Region("bbox", (0, 10, 10, 20), name="Sahel (near 15.0°N, 5.0°E)"),
            "criterion": "temperature", "why": "sweep cell", "literature_place": "Sahel"}
    drv = {"status": "ok", "links": [{"driver_id": "global_soil_moisture", "driver_name": "Soil moisture",
                                      "lag_months": 1, "partial_r": -0.4, "p_fdr": 0.001, "significant": True,
                                      "plain_language": "Air temperature anomalies are associated with Soil moisture "
                                                        "anomalies 1 month earlier."}],
           "plain_language": "Consistent with Soil moisture (association, not a cause)."}
    pre = pre or {"status": "ok", "items": [{"title": "Preprint", "stance": "rising", "label": sources.PREPRINT_LABEL}],
                  "sources": [], "label": sources.PREPRINT_LABEL}
    nw = nw or {"status": "unavailable", "items": [], "label": sources.NEWS_LABEL,
                "sources": [{"source": "GDELT", "status": "unavailable", "reason": "TimeoutError"}]}
    out = B.outlook(ms, "Air temperature")
    return B.build_brief(finding_id="f1", cand=cand, trend=trend, research=research(list(gap_papers)), pre=pre, nw=nw,
                         drv=drv, out=out, provenance={"dataset_short_name": "x"},
                         request={"start": "2000-01", "end": "2024-12", "alpha": 0.05})


def test_brief_structure_and_numbers_from_engines():
    b = _brief()
    for k in ("title", "potential_discovery", "discovery_label", "what", "where", "since", "rate", "verdict",
              "drivers", "literature", "preprints", "news", "figure", "outlook", "summary", "reproduce", "limits"):
        assert k in b, k
    assert b["potential_discovery"] is True
    assert b["verdict"]["label"] == "VERIFIED" and b["verdict"]["limit"]
    assert b["since"]["date"] == "2012-05" and b["figure"]["change_date"] == "2012-05"
    assert b["rate"]["per_decade"] == 0.52 and b["rate"]["units"] == "°C"
    assert len(b["figure"]["time"]) == len(b["figure"]["observed"]) == N
    assert b["literature"]["related_works"][0]["doi_url"] == "https://doi.org/10.1/x"
    o = b["outlook"]
    assert o["status"] == "ok" and o["label"] == B.OUTLOOK_LABEL and o["disclaimer"]
    assert len(o["years"]) == len(o["p05"]) == len(o["p50"]) == len(o["p95"]) >= 20
    assert all(lo <= md <= hi for lo, md, hi in zip(o["p05"], o["p50"], o["p95"]))
    assert o["unreviewed_context"]["label"] == B.UNREVIEWED_LABEL
    assert "News search was unavailable" in o["unreviewed_context"]["plain_language"]
    json.dumps(b)                                                       # JSON-ready


def test_wording_never_overclaims():
    b = _brief()
    text = json.dumps(b, ensure_ascii=False).lower()
    for bad in ("caused by", "confirmed discovery", "discovery confirmed", "will keep rising"):
        assert bad not in text, bad
    assert "prediction" not in text.replace("not a prediction", "")
    generated = [b["title"], b["summary"]["text"], b["gap"]["plain_language"], b["outlook"]["plain_language"],
                 b["outlook"]["unreviewed_context"]["plain_language"], b["drivers"]["plain_language"],
                 *[lk["plain_language"] for lk in b["drivers"]["links"]]]
    assert all(B.wording_ok(t) for t in generated), generated
    assert "associated with" in b["drivers"]["links"][0]["plain_language"]
    assert B.POTENTIAL_LABEL in b["gap"]["plain_language"]
    assert not B.wording_ok("This change was caused by deforestation.")
    assert not B.wording_ok("Our prediction is 2 °C more.")
    assert B.wording_ok("Simulated, not a prediction.")


def test_ai_summary_kept_only_when_number_checked(client):
    st = client.app.state.etd
    b = _brief()
    facts = B.facts_for(b)
    ref = b["summary"]["text"]
    client.fake.llm_reply = "Air temperature in the Sahel rose by 9.9 °C per decade, caused by dust."
    assert asyncio.run(B.ai_summary(st, facts, ref))["source"] == "template"
    client.fake.llm_reply = ("Air temperature in the Sahel is rising by about 0.52 °C per decade over 2015 to 2024. "
                             "It is VERIFIED: it passed every check.")
    out = asyncio.run(B.ai_summary(st, facts, ref))
    assert out["source"] == "local_llm" and out["label"] == "AI-written, number-checked"
    client.fake.llm_reply = ("Air temperature in the Sahel is rising by about 0.52 °C per decade over 2015 to 2024. "
                             "It is VERIFIED and no published study covers it.")      # novelty claim: not checkable
    assert asyncio.run(B.ai_summary(st, facts, ref))["source"] == "template"
    client.fake.llm_reply = ("Air temperature in the Sahel is rising by about 0.52 °C per decade over 2015 to 2024. "
                             "It is VERIFIED.")
    out = asyncio.run(B.ai_summary(st, facts, ref))
    assert out["source"] == "local_llm" and out["label"] == "AI-written, number-checked"


def test_notebook_is_valid_ipynb_json():
    b = _brief()
    nb = json.loads(json.dumps(build_notebook(b, "http://127.0.0.1:8000/", "j_0123456789abcdef")))
    assert nb["nbformat"] == 4 and nb["metadata"]["kernelspec"]["name"] == "python3"
    assert {c["cell_type"] for c in nb["cells"]} == {"markdown", "code"}
    for c in nb["cells"]:
        assert isinstance(c["source"], list) and all(isinstance(s, str) for s in c["source"])
        if c["cell_type"] == "code":
            assert c["outputs"] == [] and c["execution_count"] is None
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    compile(code, "notebook", "exec")                                   # syntactically valid Python
    assert 'API = "http://127.0.0.1:8000"' in code and "token" not in code.lower()
    assert "not a prediction" in "".join("".join(c["source"]) for c in nb["cells"])


# ------------------------------------------------------------------ failing sources never crash
def _http(handler, tmp_path) -> ResilientHTTP:
    s = Settings(data_dir=tmp_path / "d", http_backoff_base_s=0.01, http_max_retries=1, _env_file=None)
    s.ensure_dirs()
    return ResilientHTTP(s, transport=httpx.MockTransport(handler))


def test_failed_news_and_preprint_sources_are_listed_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "GDELT_MIN_INTERVAL_S", 0.0)

    def down(request):
        if request.url.host == "api.gdeltproject.org":
            return httpx.Response(200, text="Your search contained a phrase that is too short.")
        return httpx.Response(503, text="down")
    http = _http(down, tmp_path)
    nw = asyncio.run(sources.news(http, variable_id="merra2_t2m", variable_name="Air temperature", place="Sahel",
                                  criterion="temperature"))
    assert nw["status"] == "unavailable" and nw["items"] == [] and nw["sources"][0]["source"] == "GDELT"
    pre = asyncio.run(sources.preprints(http, variable_id="merra2_t2m", variable_name="Air temperature", place="Sahel",
                                        since_year=2016, direction="rising"))
    assert pre["status"] == "unavailable" and {s["status"] for s in pre["sources"]} == {"unavailable"}
    b = _brief(pre=pre, nw=nw)
    assert "Preprint servers could not be searched" in b["outlook"]["unreviewed_context"]["plain_language"]


def test_news_and_preprints_parse_and_label(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "GDELT_MIN_INTERVAL_S", 0.0)

    def ok(request):
        h = request.url.host
        if h == "api.gdeltproject.org":
            return httpx.Response(200, json={"articles": [{"url": "https://n.example/a", "title": "Heat in the Sahel",
                                                           "seendate": "20261101T120000Z", "domain": "n.example"}]})
        if h == "api.openalex.org":
            return httpx.Response(200, json={"results": [{"id": "W1", "doi": "https://doi.org/10.2/p",
                                                          "title": "Sahel air temperature rising",
                                                          "abstract_inverted_index": {"Air": [0], "temperature": [1],
                                                                                      "increased": [2], "in": [3],
                                                                                      "Sahel.": [4]},
                                                          "publication_year": YEAR}]})
        return httpx.Response(500)
    http = _http(ok, tmp_path)
    nw = asyncio.run(sources.news(http, variable_id="merra2_t2m", variable_name=None, place="Sahel",
                                  criterion="temperature"))
    assert nw["status"] == "ok" and nw["items"][0]["date"] == "2026-11-01"
    assert nw["items"][0]["label"] == sources.NEWS_LABEL and "(heatwave OR temperature)" in nw["query"]
    pre = asyncio.run(sources.preprints(http, variable_id="merra2_t2m", variable_name=None, place="Sahel",
                                        since_year=2016, direction="rising"))
    assert pre["status"] == "ok" and pre["items"][0]["peer_reviewed"] is False
    assert pre["items"][0]["doi"] == "10.2/p" and pre["items"][0]["label"] == sources.PREPRINT_LABEL
    assert any(s["status"] == "unavailable" for s in pre["sources"])      # arXiv 500 listed, not raised


# ------------------------------------------------------------------ the API job end to end (offline)
def test_discovery_api_job_events_and_notebook(client, monkeypatch):
    monkeypatch.setattr(sources, "GDELT_MIN_INTERVAL_S", 0.0)
    st = client.app.state.etd
    ms = series(0.06, seed=1)
    r = client.post("/api/timeseries/upload", json={"time": [str(t.date()) for t in IDX], "value": list(ms.value),
                                                     "units": "°C", "label": "warming"})
    sid = r.json()["series_id"]

    async def fake_build(vid, region, start, end, **kw):
        if vid == "merra2_t2m":
            return {"series_id": sid, "cached": True, "completeness": None}
        from backend.core.errors import UpstreamUnavailable
        raise UpstreamUnavailable(f"{vid} offline in tests")
    st.ts.build_series = fake_build
    client.fake.llm_reply = "This warming was caused by the sun."              # must be rejected -> template
    body = {"prompt": "heat", "bbox": [0, 8, 12, 20], "region_name": "Sahel", "criteria": ["temperature"],
            "start_year": 2000, "end_year": 2024, "max_findings": 1, "time_budget_s": 120}
    r = client.post("/api/discovery", json=body)
    assert r.status_code == 202, r.text
    start = r.json()
    assert start["plan"]["mode"] == "region" and start["plan"]["direct"][0]["variable_id"] == "merra2_t2m"
    assert start["plan"]["sweeps"][0]["variable_id"] == "global_t2m"           # 144 deg^2 box is also swept
    jid = start["job_id"]
    j = wait_job(client, jid, timeout=180)
    assert j["status"] == "done", j
    res = client.get(f"/api/discovery/{jid}").json()["result"]
    assert res["summary"]["findings"] == 1, res["candidates"]
    f = res["findings"][0]
    assert f["verdict"]["label"] in ("VERIFIED", "PROBABLE")
    assert f["potential_discovery"] is None          # literature hosts are unreachable offline: no flag, no guess
    assert f["summary"]["source"] == "template"
    assert f["notebook_url"] == f"/api/discovery/{jid}/notebook/f1"
    # the dead ERDDAP sweep grid and the dead news/literature sources are listed, not fatal
    assert any(s["status"] == "failed" for s in res["sweeps"])
    assert any(s.get("source") == "GDELT" for s in res["failed_sources"])
    assert f["drivers"]["status"] == "unavailable"
    assert not re.search(r"caused by|confirmed discovery", json.dumps(res).lower())

    ev = client.get(f"/api/discovery/{jid}/events").json()
    kinds = [e["type"] for e in ev["events"]]
    assert ev["done"] and kinds[0] == "started" and kinds[-1] == "done"
    assert kinds.index("finding") < kinds.index("done") and "sweep" in kinds and "step" in kinds
    sse = client.get(f"/api/discovery/{jid}/stream").text
    assert "event: finding" in sse and "event: done" in sse

    nb = client.get(f["notebook_url"])
    assert nb.status_code == 200 and nb.headers["content-type"].startswith("application/x-ipynb+json")
    assert nb.json()["nbformat"] == 4
    assert client.get(f"/api/discovery/{jid}/notebook/f9").status_code == 404
    assert client.get("/api/discovery/j_nope/events").status_code == 404


def test_discovery_rejects_bad_requests(client):
    assert client.post("/api/discovery", json={"criteria": ["nope"]}).status_code == 422
    assert client.post("/api/discovery", json={"start_year": 2020, "end_year": 2024}).status_code == 422
    assert client.post("/api/discovery", json={"max_findings": 99}).status_code == 422


def test_years_before_any_record_are_shifted_and_said_plainly(client):
    from backend.discovery import job as D
    last = YEAR - 1
    assert D.years_from_text("africa rains from 1700 to recent one", last) == (1700, last)
    assert D.years_from_text("rain 1990 to 2010", last) == (1990, 2010)
    assert D.years_from_text("rain in Kenya", last) == (None, None)
    st = client.app.state.etd
    p = D.make_plan(st, {"prompt": "africa rains from 1700 to recent one", "bbox": [-18, -35, 52, 37],
                         "region_name": "Africa", "criteria": ["precipitation"]})
    n = p["period_notice"]
    assert n and n["asked"] == [1700, last] and p["asked_years"] == [1700, last]
    assert p["years"] == n["used"] and 1940 < n["used"][0] < 2000 and n["used"][1] == last
    assert "1700" in n["plain_language"] and str(n["used"][0]) in n["plain_language"]
    assert "no instrument or satellite record" in n["plain_language"]
    chain = p["direct"][0]["variable_ids"]                     # long request: the longest record is tried first
    starts = [int(st.catalog.variables[v]["coverage_start"][:4]) for v in chain
              if st.catalog.variables[v].get("coverage_start")]
    assert starts == sorted(starts) and starts[0] == n["used"][0]
    assert p["sweeps"][0]["variable_id"] == "global_precip_chirps"
    assert D.make_plan(st, {"bbox": [0, 8, 12, 20], "criteria": ["temperature"], "start_year": 2000,
                            "end_year": 2024})["period_notice"] is None


def test_not_kept_places_still_show_series_numbers_and_no_empty_items(client, monkeypatch):
    monkeypatch.setattr(sources, "GDELT_MIN_INTERVAL_S", 0.0)
    st = client.app.state.etd
    ms = series(0.0, seed=7)
    sid = client.post("/api/timeseries/upload", json={"time": [str(t.date()) for t in IDX], "value": list(ms.value),
                                                       "units": "°C", "label": "flat"}).json()["series_id"]

    async def fake_build(vid, region, start, end, **kw):
        if vid == "merra2_t2m":
            return {"series_id": sid, "cached": True, "completeness": None}
        from backend.core.errors import UpstreamUnavailable
        raise UpstreamUnavailable(f"{vid} offline in tests")
    st.ts.build_series = fake_build
    body = {"prompt": "heat in the Sahel from 1700 to now", "bbox": [0, 8, 12, 20], "region_name": "Sahel",
            "criteria": ["temperature"], "max_findings": 1, "time_budget_s": 120, "news": False, "preprints": False}
    r = client.post("/api/discovery", json=body)
    assert r.status_code == 202, r.text
    assert r.json()["plan"]["period_notice"]["asked"][0] == 1700
    j = wait_job(client, r.json()["job_id"], timeout=180)
    assert j["status"] == "done", j
    res = j["result"]
    assert res["findings"] == [] and res["next_steps"]
    assert "data shown below are real" in res["plain_language"]
    card = res["tested"][0]
    assert card["label"] == "NOT VERIFIED" and card["reason"] and card["note"]
    assert card["variable"]["id"] == "merra2_t2m" and card["rate"]["units"] == "°C"
    assert isinstance(card["rate"]["per_decade"], float) and card["full_record"]["plain_language"]
    assert len(card["figure"]["time"]) == len(card["figure"]["observed"]) > 100 and card["period"]
    assert card["provenance"]
    # every list the UI renders has a readable text; nothing empty
    for item in res["failed_sources"] + res["candidates"]:
        assert item["text"].strip() and not item["text"].startswith(":"), item
    assert any(s["source"].startswith("NOAA ERDDAP grid") for s in res["failed_sources"])
    ev = client.get(f"/api/discovery/{r.json()['job_id']}/events").json()["events"]
    assert any(e["type"] == "tested" and e["card"]["candidate_id"] == card["candidate_id"] for e in ev)
