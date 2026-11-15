"""POST /api/report: contract, section order, keyless fallback, trend map and number-checked AI text, offline.

ERDDAP is served by a synthetic grid (NCEP Gaussian latitudes, 0..360 longitudes, planted warming), so the
ERDDAP connector's fetch and fetch_cube run for real against it."""
import re
from urllib.parse import unquote

import httpx
import numpy as np
import pandas as pd
import pytest

from backend.core.config import Settings
from backend.report import SECTION_ORDER
from backend.report import builder
from tests.conftest import wait_job
from tests.fakes import FakeUpstream

LAT = np.linspace(88.5, -88.5, 94)
LON = np.arange(0.0, 358.2, 1.875)
TIMES = pd.date_range("1990-01-01", "2024-12-01", freq="MS")
TREND_K_PER_YEAR = 0.03
QUESTION = "How has temperature changed in India from 2002 to 2022?"


def erddap_csv(query: str) -> str:
    m = re.match(r"(\w+)\[(\d+):1:(\d+)\](?:\[\([^)]*\)\])?\[(\d+):(\d+):(\d+)\]\[(\d+):(\d+):(\d+)\]", query)
    var, a, b, i0, si, i1, j0, sj, j1 = m.group(1), *map(int, m.groups()[1:])
    lines = [f"time,latitude,longitude,{var}", "UTC,degrees_north,degrees_east,degK"]
    rng = np.random.default_rng(a)
    for k in range(a, b + 1):
        t = TIMES[k]
        yrs = (t.year - 1990) + (t.month - 1) / 12
        for i in range(i0, i1 + 1, si):
            for j in range(j0, j1 + 1, sj):
                val = 290 + 5 * np.sin(2 * np.pi * (t.month - 4) / 12) + TREND_K_PER_YEAR * yrs + rng.normal(0, 0.3)
                lines.append(f"{t:%Y-%m-%dT00:00:00Z},{LAT[i]},{LON[j]},{val:.4f}")
    return "\n".join(lines) + "\n"


def make_handler(fake: FakeUpstream):
    def h(request: httpx.Request) -> httpx.Response:
        if request.url.host == "upwell.pfeg.noaa.gov":
            q = unquote(request.url.query.decode())
            if request.url.path.endswith(".csv0"):
                axis = q.split("[")[0]
                vals = {"time": [f"{t:%Y-%m-%dT00:00:00Z}" for t in TIMES], "latitude": LAT, "longitude": LON}[axis]
                return httpx.Response(200, text="\n".join(map(str, vals)) + "\n")
            return httpx.Response(200, text=erddap_csv(q))
        if request.url.host in ("export.arxiv.org", "api.openalex.org", "api.springernature.com",
                                "api.semanticscholar.org", "api.adsabs.harvard.edu"):
            return httpx.Response(503)
        return fake.handler(request)
    return h


@pytest.fixture
def keyless_client(tmp_path, monkeypatch):
    """No NASA / NOAA credentials at all: the planner's first temperature dataset needs one."""
    from fastapi.testclient import TestClient

    from backend.core import auth
    from backend.main import create_app
    monkeypatch.setattr(auth, "edl_basic_auth", lambda s: (_ for _ in ()).throw(auth.CredentialsMissing("no login")))
    s = Settings(data_dir=tmp_path / "data", earthdata_token=None, earthdata_username=None, earthdata_password=None,
                 noaa_cdo_token=None, http_backoff_base_s=0.01, http_max_retries=1, llm_provider="ollama",
                 llm_base_url="http://127.0.0.1:11434", min_months_for_test=120, _env_file=None)
    fake = FakeUpstream()
    tr = httpx.MockTransport(make_handler(fake))
    app = create_app(s, transport=tr, llm_transport=tr)
    with TestClient(app) as c:
        c.fake = fake
        yield c


def run_report(c, with_job=False, **body):
    r = c.post("/api/report", json={"question": QUESTION, **body})
    assert r.status_code == 202, r.text
    assert set(r.json()) >= {"job_id", "status_url", "partial_url"}
    j = wait_job(c, r.json()["job_id"], timeout=240)
    assert j["status"] == "done", j.get("error")
    return (j["result"], r.json()["job_id"]) if with_job else j["result"]


def test_report_contract_order_fallback_and_map(keyless_client):
    res = run_report(keyless_client)
    assert set(res) >= {"question", "plan", "headline", "sections", "glossary", "provenance", "limits", "ai"}
    assert set(res["plan"]) >= {"variable_id", "variable_name", "units", "region_name", "geometry", "start", "end",
                                "source"}
    assert res["plan"]["region_name"] == "India" and res["plan"]["geometry"]["type"] in ("BBox", "Polygon", "bbox")
    assert res["plan"]["start"].startswith("2002") and res["plan"]["end"].startswith("2022")
    assert res["plan"]["variable_id"] == "global_t2m"            # keyless fallback of the temperature criterion
    assert [s["id"] for s in res["sections"]] == SECTION_ORDER
    for s in res["sections"]:
        assert set(s) >= {"id", "title", "kind", "text", "data"} and s["text"]
        assert s["kind"] in ("text", "chart", "map", "checks", "table", "bars")
        assert not re.search(r"\b(caused by|because of|proven)\b", s["text"], re.I), s["text"]
    sec = {s["id"]: s for s in res["sections"]}
    assert sec["series"]["kind"] == "chart"
    assert {"observed", "deseasonalized", "sen_line", "beast_trend", "change_probability", "time"} <= set(
        sec["series"]["data"]["chart"])
    assert sec["how_much"]["data"]["rate_per_decade"] > 0 and len(sec["how_much"]["data"]["ci95_per_decade"]) == 2
    assert sec["is_it_real"]["kind"] == "checks" and sec["is_it_real"]["data"]["court"]["stamp"] in (
        "SIGNIFICANT", "NOT PROVEN")
    assert len(sec["seasons"]["data"]["values"]) == 12
    m = sec["map"]
    assert m["kind"] == "map"
    d = m["data"]
    assert d["n_cells"] >= 50 and len(d["slope_per_decade"]) == len(d["lat"])
    assert len(d["slope_per_decade"][0]) == len(d["lon"]) and len(d["significant"]) == len(d["lat"])
    assert d["area_fraction_rising"] > 0.5 and "field_significance" in d and d["units"] == "°C"
    assert abs(d["area_mean_slope_per_decade"] - TREND_K_PER_YEAR * 10) < 0.1
    assert res["headline"] and "India" in res["headline"]
    assert res["ai"] == {**res["ai"], "used": False, "label": "template", "status": "done", "pending": []}
    # wording fixes from the reviewers
    txt = " ".join(s["text"] for s in res["sections"]) + res["headline"]
    assert not re.search(r"cannot say the change is real|No detectable trend over", txt)
    assert "mk_ess_ar1" not in sec["is_it_real"]["text"] and "see why below" not in sec["is_it_real"]["text"]
    assert "would show a 95% range that excludes zero by chance alone" in sec["seasons"]["text"]
    assert "no border or land mask" in sec["map"]["text"] and "coarse" in sec["map"]["text"]
    assert "Is that a lot?" in sec["how_much"]["text"]
    assert sec["is_it_real"]["data"]["limit"] is None or sec["is_it_real"]["data"]["verdict"] == "VERIFIED"


def test_report_partial_endpoint_and_cache(keyless_client):
    res, jid = run_report(keyless_client, with_job=True)
    p = keyless_client.get(f"/api/report/{jid}/partial").json()
    assert p["ready"] and p["status"] == "done" and p["report"]["headline"] == res["headline"]
    assert keyless_client.get("/api/report/j_nope/partial").status_code == 404
    # same variables, region and period: served from the report cache
    res2 = run_report(keyless_client)
    assert res2["timing"]["cached"] and res2["headline"] == res["headline"]
    assert [s["text"] for s in res2["sections"]] == [s["text"] for s in res["sections"]]
    res3 = run_report(keyless_client, refresh=True)
    assert not res3["timing"]["cached"]


def test_ai_text_kept_only_when_number_checked(keyless_client):
    def reply(body):
        if body.get("format"):                    # planner JSON
            return {}
        return "In simple words, this part of the report shows the data for the region in a clear way for you."
    keyless_client.fake.llm_reply = reply
    res = run_report(keyless_client, variable_id="global_t2m", start="2002-01", end="2022-12")
    assert res["ai"]["used"] and res["ai"]["label"] == "AI-written, number-checked"
    for s in res["sections"]:
        if s["id"] not in builder.REWRITE_IDS:
            assert (s["text_source"], s["ai_status"]) == ("template", "not_rewritten"), s["id"]
        elif s["ai_status"] == "kept_template":       # the reply dropped an honesty caveat the template states
            assert any(rx.search(s["text"]) for rx in builder.MUST_KEEP), s["id"]
        else:
            assert (s["text_source"], s["ai_status"]) == ("local_llm", "rewritten"), s["id"]
    assert res["ai"]["sections_rewritten"] >= 2

    keyless_client.fake.llm_reply = lambda b: {} if b.get("format") else (
        "Temperatures went up by 987.6 degrees per decade, which was caused by the sun.")
    res = run_report(keyless_client, variable_id="global_t2m", start="2002-01", end="2022-12", refresh=True)
    assert not res["ai"]["used"] and res["ai"]["label"] == "template"
    assert all("987.6" not in s["text"] for s in res["sections"])


def test_report_rejects_off_topic(keyless_client):
    r = keyless_client.post("/api/report", json={"question": "What is the best pizza topping in Naples?"})
    assert r.status_code == 422


def test_partials_publish_deterministic_first_then_ai(keyless_client):
    """build_report publishes the template report before any AI wording, then one update per rewritten section."""
    import asyncio
    keyless_client.fake.llm_reply = lambda b: {} if b.get("format") else (
        "In simple words, this part of the report shows the data for the region in a clear way for you.")
    st = keyless_client.app.state.etd
    snaps = []

    async def go():
        return await builder.build_report(st, question=QUESTION, refresh=True, on_partial=snaps.append)
    res = keyless_client.portal.call(go) if hasattr(keyless_client, "portal") and keyless_client.portal else         asyncio.run(go())
    assert snaps[0]["ai"]["status"] == "writing" and snaps[0]["ai"]["pending"] == builder.REWRITE_IDS
    assert all(s["text_source"] == "template" for s in snaps[0]["sections"])
    assert len(snaps) >= 1 + len(builder.REWRITE_IDS)
    assert snaps[-1]["ai"]["status"] == "done" and res["ai"]["sections_rewritten"] >= 2
    assert all(s["ai_status"] != "pending" for s in res["sections"])


def test_late_break_softened_and_research_sentence():
    class MS:
        time = pd.date_range("2002-01-01", "2022-12-01", freq="MS")
    onset = {"events": [{"date": "2020-03", "status": "confirmed", "probability": 1.0, "agrees_with_pelt": False,
                         "interval90": ["2019-09", "2021-10"]},
                        {"date": "2010-09", "status": "confirmed", "agrees_with_pelt": True,
                         "interval90": ["2010-01", "2011-01"]}],
             "segments": [{"slope_per_decade": 0.35, "ci95_adj_per_decade": [0.18, 0.52]},
                          {"slope_per_decade": 1.8, "ci95_adj_per_decade": [-1.4, 5.0]}]}
    view = {"markers": [{"date": "2020-03", "kind": "beast_confirmed"}, {"date": "2010-09", "kind": "beast_confirmed"}]}
    o, v = builder._soften_late_breaks(onset, view, MS)
    assert [e["status"] for e in o["events"]] == ["possible", "confirmed"] and o["events"][0]["late_in_record"]
    assert [m["kind"] for m in v["markers"]] == ["beast_possible", "beast_confirmed"]
    rs = {"sources": [{"status": "ok"}], "since_year": 2016,
          "agreement": {"label": "supported", "n_supporting": 3, "n_conflicting": 0},
          "papers": [{"stance": "rising", "authors": ["ARGHA GHOSH", "X Y"], "year": 2025},
                     {"stance": "rising", "authors": [], "year": 2022}]}
    txt = builder._research_sentence(rs, "rising", "air temperature", "India")
    assert "Ghosh et al. 2025" in txt and "Unknown" not in txt and "opposite" not in txt


def test_rewrite_must_keep_caveats_and_complete_sentences():
    assert not builder._wording_ok("The rise is consistent with natural swings.", "x")
    assert not builder._wording_ok("Temperatures rose.", "The tests cannot yet rule out that swings produced this.")
    assert builder._wording_ok("We cannot yet rule out natural swings.", "The tests cannot yet rule out that x.")
    assert not builder._wording_ok("The change is not real yet.", "x")
    assert builder._complete_sentences("One. Two. PELT splits the") == "One. Two."



def test_shift_period_answers_years_before_any_record():
    from types import SimpleNamespace
    from backend.report.builder import shift_period
    st = SimpleNamespace(catalog=SimpleNamespace(variables={"a": {"coverage_start": "1998-01"}, "b": {"coverage_start": "1948-01"}}))
    s0, s1, note = shift_period(st, ["a", "b"], "1600-01", "1700-12")
    assert s0 == "1998-01" and note.startswith("shifted: you asked for 1600-1700") and "1998" in note
    assert shift_period(st, ["a", "b"], "2002-01", "2022-12") is None
