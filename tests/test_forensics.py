"""Trend Forensics: calibrated BEAST change dating, PCMCI+ suspects, claim verifier, question intents."""
import numpy as np
import pandas as pd

from backend.ai.assistant import detect_wishes, intents_of
from backend.ai.verify import verify_text
from backend.insights.causal import causal_screen, judge_suspects
from backend.insights.onset import change_onset
from backend.timeseries.model import MonthlySeries, Provenance

N = 288
IDX = pd.date_range("2001-01-01", periods=N, freq="MS")
T = np.arange(N) / 12


def ar(phi, sd, seed):
    rng = np.random.default_rng(seed)
    e = np.zeros(N)
    for i in range(1, N):
        e[i] = phi * e[i - 1] + rng.normal(0, sd)
    return e


def ms(y, vid=None):
    return MonthlySeries(IDX, np.asarray(y, float), "x", Provenance("test", "x", {}), variable_id=vid, label=vid)


def test_onset_dates_a_real_change_and_flags_nearby_seam():
    y = 2 * np.sin(2 * np.pi * T) + 0.02 * T + np.where(T >= 13, 0.5 + 0.12 * (T - 13), 0) + ar(0.4, 0.3, 3)
    y[[10, 50, 51]] = np.nan                                  # gaps are allowed, never filled
    r = change_onset(ms(y), seams=[{"id": "s", "date": "2014-06", "description": "seam"}])
    conf = [e for e in r["events"] if e["status"] == "confirmed"]
    assert len(conf) == 1
    e = conf[0]
    assert e["interval90"][0] <= "2014-01" <= e["interval90"][1]   # truth inside the interval
    assert e["kind"] == "acceleration" and e["near_seam"]["label"] == "possible instrument effect"
    assert len(r["ribbon"]["change_probability"]) == N


def test_onset_no_false_change_in_persistent_steady_trend():
    y = 2 * np.sin(2 * np.pi * T) + 0.03 * T + 0.4 * ar(0.6, 1.0, 11)
    r = change_onset(ms(y))
    assert not any(e["status"] == "confirmed" for e in r["events"])


def test_onset_too_short():
    assert change_onset(ms(np.r_[np.ones(40), np.full(N - 40, np.nan)]))["status"] == "too_short"


def test_pcmci_supports_true_driver_and_rejects_unrelated():
    rng = np.random.default_rng(5)
    rain, temp = ar(0.3, 1, 1), ar(0.5, 1, 2)
    soil = np.zeros(N)
    ndvi = np.zeros(N)
    for i in range(1, N):
        soil[i] = 0.6 * soil[i - 1] + 0.7 * rain[i] + rng.normal(0, 0.5)
        ndvi[i] = 0.4 * ndvi[i - 1] + 0.6 * soil[i - 1] + rng.normal(0, 0.5)
    s = lambda y, v: ms(y + np.sin(2 * np.pi * T) + 0.02 * T, v)  # noqa: E731
    screen = causal_screen(s(ndvi, "ndvi"), [s(soil, "soil"), s(temp, "temp")], tau_max=3)
    j = judge_suspects(screen, [{"driver_id": "soil", "expected_sign": "+"},
                                {"driver_id": "temp", "expected_sign": "-"}])
    st = {x["driver_id"]: x for x in j["suspects"]}
    assert st["soil"]["status"] == "supported" and st["soil"]["lag_months_found"] == 1
    assert st["temp"]["status"] == "not_supported"
    assert "not proof of cause" in j["plain_language"]


def test_verifier_blocks_causation_wrong_direction_and_unsupported_numbers():
    facts = {"direction": "rising", "significant": False, "rate_per_decade": 0.25, "period": ["2001-01", "2024-12"]}
    ok = verify_text("Rising about 0.25 per decade since 2001, but not statistically significant yet.", facts)
    assert ok["passed"], ok
    assert not verify_text("Rainfall caused this rise of 0.25 per decade.", facts)["passed"]
    assert not verify_text("It is falling by 0.25 per decade.", facts)["passed"]
    assert not verify_text("A statistically significant rise of 0.25 per decade.", facts)["passed"]
    assert not verify_text("Rising 0.9 per decade.", facts)["passed"]


def test_question_intents():
    i = intents_of(detect_wishes("When did rainfall in Chennai start to change, and why?"))
    assert "when" in i and "why" in i
    assert "how_long" in intents_of(detect_wishes("How many more years until the trend is significant yet?"))
    assert intents_of(detect_wishes("Is NDVI changing in Kenya?")) == ["what"]


def test_onset_and_suspects_endpoints(client):
    y = (2 * np.sin(2 * np.pi * T) + 0.02 * T + ar(0.3, 0.3, 4)).tolist()
    sid = client.post("/api/timeseries/upload", json={"time": [d.strftime("%Y-%m") for d in IDX], "value": y,
                                                       "units": "x", "label": "t"}).json()["series_id"]
    r = client.get(f"/api/analyze/{sid}/onset?n_surrogates=19").json()
    assert r["status"] == "ok" and "plain_language" in r
    s = client.post("/api/ai/suspects", json={"variable_id": "modis_ndvi_monthly"}).json()
    assert s["suspects"] and all(x["driver_id"] != "modis_ndvi_monthly" for x in s["suspects"])


def test_investigate_when_and_why_question_end_to_end(client):
    from tests.conftest import wait_job
    r = client.post("/api/investigate", json={"question": "When did rainfall in Chennai start to change since 2001, and why?"})
    j = wait_job(client, r.json()["job_id"], timeout=180)
    assert j["status"] == "done", j
    res = j["result"]
    assert {"what", "when", "why"} <= set(res["answer"]["intents"])
    assert [s["intent"] for s in res["answer"]["sections"]][:2] == ["what", "when"]
    assert res["why"]["protocol"].startswith("suspects were fixed before any data")
    assert "onset" in res["results"][0]["insights"]
