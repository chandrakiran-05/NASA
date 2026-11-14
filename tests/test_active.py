"""Active trends: detection, independent checks, BEAST gate, verdict labels, live events API."""
import json

import numpy as np
import pandas as pd
import pytest

from backend.active import engine, runner
from backend.timeseries.model import MonthlySeries, Provenance
from tests.conftest import wait_job

N = 25 * 12
T = np.arange(N) / 12
IDX = pd.date_range("2000-01-01", periods=N, freq="MS")


def series(signal, seed=0, phi=0.3, sd=0.4) -> MonthlySeries:
    rng = np.random.default_rng(seed)
    e = np.zeros(N)
    z = rng.normal(0, sd, N)
    for i in range(1, N):
        e[i] = phi * e[i - 1] + z[i]
    return MonthlySeries(time=IDX, value=signal + 4 * np.sin(2 * np.pi * T) + e, units="°C",
                         provenance=Provenance(source_api="user", variable="v", geometry={}))


def test_detect_states():
    assert engine.detect(series(0.05 * T))["state"] == "active"
    em = engine.detect(series(np.where(T > 15, 0.2 * (T - 15), 0.0)))
    assert em["state"] in ("emerging", "accelerating") and em["direction"] == "rising"
    rev = engine.detect(series(np.where(T < 13, 0.1 * T, 1.3 - 0.12 * (T - 13)), seed=3))
    assert rev["state"] == "reversed" and rev["direction"] == "falling"
    stalled = engine.detect(series(np.where(T < 13, 0.15 * T, 1.95), seed=4))
    assert stalled["state"] == "stalled" and not stalled["active"]
    assert engine.detect(MonthlySeries(time=IDX[:120], value=np.ones(120), units=None,
                                       provenance=Provenance(source_api="user", variable="v", geometry={})))["state"] == "too_short"


def test_steady_trend_passes_every_check_and_beast():
    ms = series(0.05 * T, seed=1)
    d = engine.detect(ms)
    checks = [engine.check_integrity(ms, d), engine.check_court(ms, d, 0.05), engine.check_chance(ms, d, 0.05),
              engine.check_stability(ms, d, 0.05)]
    assert all(c["status"] == "pass" for c in checks), checks
    from backend.insights.onset import change_onset
    b = engine.beast_gate(change_onset(ms, n_surrogates=19), d)
    assert b["status"] == "agrees"
    assert engine.label(d, checks, b)["label"] == "VERIFIED"


def _onset(rising=0.9, events=(), segments=()):
    return {"status": "ok", "current_direction_probability": {"rising": rising, "flat": 0.0, "falling": 1 - rising},
            "events": list(events), "segments": list(segments)}


def test_beast_gate_and_label_rules():
    d = {"direction": "rising", "plain_language": "Rising now."}
    assert engine.beast_gate(_onset(0.9), d)["status"] == "agrees"
    assert engine.beast_gate(_onset(0.1), d)["status"] == "disagrees"
    assert engine.beast_gate(_onset(0.5), d)["status"] == "uncertain"
    # the regime after the last confirmed change decides over the last-year posterior
    ev = {"status": "confirmed", "date": "2015-03", "interval90": ["2014-01", "2016-01"], "probability": 0.9,
          "near_seam": {"label": "possible instrument effect"}}
    seg = [{"slope_per_decade": 0.1, "significant": True}, {"slope_per_decade": -0.4, "significant": True}]
    g = engine.beast_gate(_onset(0.9, [ev], seg), d)
    assert g["status"] == "disagrees" and g["active_since"]["date"] == "2015-03"
    ok = [engine.make_check(n, "pass", "") for n in ("integrity", "court", "chance", "stability")]
    assert engine.label(d, ok, engine.beast_gate(_onset(0.9), d))["label"] == "VERIFIED"
    assert engine.label(d, ok, engine.beast_gate(_onset(0.5), d))["label"] == "PROBABLE"
    seg_up = [{"slope_per_decade": 0.0, "significant": False}, {"slope_per_decade": 0.4, "significant": True}]
    assert engine.label(d, ok, engine.beast_gate(_onset(0.9, [ev], seg_up), d))["label"] == "PROBABLE"   # seam
    bad = ok[:3] + [engine.make_check("stability", "fail", "")]
    assert engine.label(d, bad, engine.beast_gate(_onset(0.9), d))["label"] == "NOT VERIFIED"
    # the AI reviewer is advisory: it can never change the label
    adv = ok + [engine.make_check("ai_review", "warn", "")]
    assert engine.label(d, adv, engine.beast_gate(_onset(0.9), d))["label"] == "VERIFIED"


def test_cross_variable_checks():
    up = {"active": True, "rate_per_decade": 1.0, "state": "active", "recent": {"significant": True}}
    down = {**up, "rate_per_decade": -1.0}
    links = [{"a": "x", "b": "y", "expected_sign": 1, "why": "linked"}]
    assert engine.check_physics("x", {"x": up, "y": up}, links)["status"] == "pass"
    assert engine.check_physics("x", {"x": up, "y": down}, links)["status"] == "warn"
    assert engine.check_physics("x", {"x": up}, links)["status"] == "skipped"
    groups = [{"members": ["x", "y"]}]
    assert engine.check_second_opinion("x", {"x": up, "y": up}, groups)["status"] == "pass"
    assert engine.check_second_opinion("x", {"x": up, "y": down}, groups)["status"] == "warn"


def test_criteria_cover_all_28_and_plan_is_honest(settings):
    from backend.catalog.catalog import load_catalog
    from backend.core.geometry import parse_geometry
    from backend.timeseries.service import parse_date
    cat = load_catalog()
    view = runner.criteria_view(cat)
    assert [c["n"] for c in view] == list(range(1, 29))
    assert {c["id"] for c in view if c["status"] == "not_trendable"} == {"oil_pollution", "radar_backscatter",
                                                                       "maritime_activity"}
    pt = parse_geometry({"type": "Point", "coordinates": [80.27, 13.08]})
    items, skipped = runner.plan(cat, pt, parse_date("1995-01"), parse_date("2024-12", end=True),
                                 criteria=["temperature", "oil_pollution"], variable_ids=None, per_criterion=1,
                                 options={})
    assert items == [{"variable_id": "merra2_t2m", "criteria": ["temperature"]}]
    assert skipped[0]["criterion"] == "oil_pollution" and skipped[0]["where_to_look"]
    _, sk = runner.plan(cat, pt, parse_date("2016-01"), parse_date("2024-12", end=True), criteria=["soil_moisture"],
                        variable_ids=None, per_criterion=1, options={})
    assert all("needs 15 years" in s["reason"] for s in sk)
    with pytest.raises(Exception):
        runner.plan(cat, pt, parse_date("1995-01"), parse_date("2024-12", end=True), criteria=["nope"],
                    variable_ids=None, per_criterion=1, options={})


def _upload(client, values, label):
    r = client.post("/api/timeseries/upload", json={"time": [str(t.date()) for t in IDX], "value": list(values),
                                                     "units": "°C", "label": label})
    assert r.status_code == 200, r.text
    return r.json()["series_id"]


def test_api_live_events_sse_and_reuse(client):
    client.fake.llm_reply = {"concerns": ["model_not_observation"], "note": "Consistent with a warming region."}
    a = _upload(client, series(0.05 * T, seed=1).value, "warming")
    b = _upload(client, series(0 * T, seed=7).value, "flat")
    body = {"series_ids": [a, b], "ai_review": True}
    r = client.post("/api/active-trends", json=body)
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    j = wait_job(client, jid, timeout=120)
    assert j["status"] == "done", j
    res = j["result"]
    assert res["summary"]["variables"] == 2
    top = res["trends"][0]
    assert top["series_id"] == a and top["verdict"]["label"] == "VERIFIED"
    assert {c["check"] for c in top["checks"]} >= {"integrity", "court", "chance", "stability", "fdr"}
    assert top["ai_review"]["status"] == "warn" and top["ai_review"]["detail"]["advisory"]
    assert any(n["series_id"] == b for n in res["not_active"]) or any(t["series_id"] == b for t in res["trends"])
    # Research Evidence ran (sources unreachable in tests -> reported, not fatal) and the best trend is chosen
    assert top["research"]["agreement"]["label"] in ("no_literature", "inconclusive")
    assert res["best_trend"]["best"]["variable_id"] == top["variable_id"]

    ev = client.get(f"/api/active-trends/{jid}/events", params={"after": 0}).json()
    kinds = [e["type"] for e in ev["events"]]
    assert ev["done"] and kinds[0] == "started" and kinds[-1] == "done"
    mine = [e["type"] for e in ev["events"] if e.get("variable_id") == a]
    assert mine.index("candidate") < mine.index("check") < mine.index("beast") < mine.index("verdict")
    assert [e["seq"] for e in ev["events"]] == list(range(len(kinds)))

    sse = client.get(f"/api/active-trends/{jid}/stream").text
    assert sse.count("event: ") == len(kinds) and "event: done" in sse
    first = json.loads(sse.split("data: ", 1)[1].split("\n", 1)[0])
    assert first["type"] == "started"

    assert client.post("/api/active-trends", json=body).json()["job_id"] != jid       # finished: runs again
    assert client.get("/api/active-trends/j_nope/events").status_code == 404


def test_api_fetch_path_and_validation(client):
    geom = {"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"}
    r = client.post("/api/active-trends", json={"geometry": geom, "start": "1995-01", "end": "2024-12",
                                                "criteria": ["temperature"], "ai_review": False})
    assert r.status_code == 202, r.text
    assert r.json()["variables"] == ["merra2_t2m"]
    j = wait_job(client, r.json()["job_id"], timeout=120)
    assert j["status"] == "done", j
    assert j["result"]["summary"]["variables"] == 1 and not j["result"]["failed"]
    assert client.post("/api/active-trends", json={"criteria": ["temperature"]}).status_code == 422
    assert client.get("/api/criteria").json()["criteria"][9]["id"] == "oil_pollution"


def test_deep_review_and_hardware(client, settings):
    from backend.ai.deep_llm import DeepLLM
    st = client.app.state.etd
    sid = _upload(client, series(0.05 * T, seed=1).value, "warming")
    jid = client.post("/api/active-trends", json={"series_ids": [sid], "ai_review": False}).json()["job_id"]
    assert wait_job(client, jid, timeout=120)["status"] == "done"
    assert client.post(f"/api/active-trends/{jid}/deep-review").status_code == 422      # tier off by default
    st.deep = DeepLLM(settings.model_copy(update={"deep_llm_provider": "airllm", "deep_llm_model": "fake"}),
                      loader=lambda m, s: lambda msgs, n: '{"concerns": ["short_record"], "note": "Looks consistent."}')
    r = client.post(f"/api/active-trends/{jid}/deep-review")
    assert r.status_code == 202, r.text
    rev = wait_job(client, r.json()["job_id"])["result"]["reviews"][0]
    assert rev["check"] == "deep_review" and rev["detail"]["concerns"] == ["short_record"]
    ev = client.get(f"/api/active-trends/{jid}/events").json()["events"]
    assert ev[-1]["type"] == "deep_review"
    hw = client.get("/api/ai/hardware").json()
    assert "live" in hw["recommendation"] and "disk_path" not in hw["profile"]


def test_runner_falls_back_to_next_variable_of_the_criterion(client):
    from backend.core.errors import CredentialsMissing
    st = client.app.state.etd
    real = st.ts.build_series

    async def flaky(vid, *a, **k):
        if vid == "merra2_t2m":
            raise CredentialsMissing("needs a free NASA Earthdata token")
        return await real(vid, *a, **k)
    st.ts.build_series = flaky
    geom = {"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"}
    jid = client.post("/api/active-trends", json={"geometry": geom, "start": "1995-01", "end": "2024-12",
                                                  "criteria": ["temperature"], "ai_review": False,
                                                  "research": False}).json()["job_id"]
    res = wait_job(client, jid, timeout=120)["result"]
    used = [t["variable_id"] for t in res["trends"]] + [t["variable_id"] for t in res["not_active"]]
    assert used and used[0] != "merra2_t2m" and "merra2_t2m" in res["failed"]
    ev = client.get(f"/api/active-trends/{jid}/events").json()["events"]
    assert any(e["type"] == "fallback" and e["instead_of"] == "merra2_t2m" for e in ev)


def test_view_has_chart_beast_pelt_and_ai_text(client):
    client.fake.llm_reply = "Temperature here is rising, consistent with the computed trend."
    sid = _upload(client, series(0.05 * T, seed=1).value, "warming")
    v = client.get(f"/api/view/{sid}").json()
    n = len(v["chart"]["time"])
    assert n == 300 and len(v["chart"]["observed"]) == n and len(v["chart"]["change_probability"]) == n
    assert v["caption"] and v["explanation"]["text"] and v["explanation"]["source"] in ("local_llm", "deterministic")
    assert all(m["kind"].startswith(("beast_", "pelt_")) for m in v["markers"])
    jid = client.post("/api/active-trends", json={"series_ids": [sid], "ai_review": False}).json()["job_id"]
    tr = wait_job(client, jid, timeout=120)["result"]["trends"][0]
    assert tr["view"]["chart"]["time"] and tr["view"]["recent_window"]


def test_printable_card_and_method_papers(client):
    import xml.etree.ElementTree as ET
    sid = _upload(client, series(0.05 * T, seed=1).value, "warming <test>")
    r = client.get(f"/api/view/{sid}/card.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    root = ET.fromstring(r.text)                       # valid XML, label escaped
    assert root.tag.endswith("svg") and "warming &lt;test&gt;" in r.text and "Verdict" in r.text
    m = client.get("/api/research/methods").json()
    assert "papers" in m and m["plain_language"]
