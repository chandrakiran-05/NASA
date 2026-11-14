"""Twin engineer tools: compound thresholds, scenario sets, knob sensitivity, deletes."""
from backend.twin import scenarios
from tests.test_twin import _data, _twin

SEA = {"variable": "sea_level", "value": 0.35}
TEMP = {"variable": "temperature", "value": 22.0}


def _setup(client):
    tid = _twin(client)
    _data(client, tid)
    return tid


def _sim_p(client, tid, var, value, **knobs):
    r = client.post(f"/api/twin/{tid}/simulate",
                    json={"n_runs": 200, "scenario": {var: {"threshold": {"value": value}, **knobs}}})
    assert r.status_code == 200, r.text
    return r.json()["variables"][var]["threshold"]["probability_by_end"]


def test_compound_matches_simulate_and_is_bounded(client):
    tid = _setup(client)
    for c in (SEA, TEMP):
        r = client.post(f"/api/twin/{tid}/compound", json={"n_runs": 200, "conditions": [c]})
        assert r.status_code == 200, r.text
        assert r.json()["probability_by_end"] == _sim_p(client, tid, c["variable"], c["value"])
    r = client.post(f"/api/twin/{tid}/compound", json={"n_runs": 200, "conditions": [SEA, TEMP]}).json()
    assert r["label"] == "simulated" and r["disclaimer"]
    assert r["probability_by_end"] <= min(c["probability_by_end"] for c in r["conditions"])
    assert all(0 <= y["p"] <= 1 for y in r["probability_same_year"])
    bad = client.post(f"/api/twin/{tid}/compound", json={"conditions": [{"variable": "nope", "value": 1}]})
    assert bad.status_code == 422


def test_scenarios_and_stronger_trend_never_lowers_crossing(client):
    tid = _setup(client)
    ps = [_sim_p(client, tid, "sea_level", 0.35, trend_multiplier=m) for m in (1, 2, 4)]
    assert ps == sorted(ps) and ps[-1] > ps[0]
    th = {"threshold": {"value": 0.35}}
    r = client.post(f"/api/twin/{tid}/scenarios", json={"n_runs": 200, "scenarios": {
        "low": {"sea_level": th}, "mid": {"sea_level": {**th, "trend_multiplier": 2}},
        "high": {"sea_level": {**th, "trend_multiplier": 4}}}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["label"] == "simulated" and j["disclaimer"]
    s = j["scenarios"]
    assert [s[k]["sea_level"]["threshold"]["probability_by_end"] for k in ("low", "mid", "high")] == ps
    assert s["high"]["sea_level"]["p50"][-1] > s["low"]["sea_level"]["p50"][-1]


def test_sensitivity_ranks_and_caps(client):
    tid = _setup(client)
    sc = {"temperature": {"trend_add_per_decade": 0.5},
          "sea_level": {"threshold": {"value": 0.35}, "trend_multiplier": 3,
                        "drivers": [{"from": "temperature", "coefficient": 0.001}]}}
    r = client.post(f"/api/twin/{tid}/sensitivity", json={"target": "sea_level", "n_runs": 100, "scenario": sc})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["label"] == "simulated" and "interact" in j["note"] and len(j["ranking"]) == 3
    assert j["ranking"][0]["knob"] == "trend_multiplier"
    ch = [abs(x["change"]) for x in j["ranking"]]
    assert ch == sorted(ch, reverse=True)
    # 11 knobs: over the cap of 10
    many = {"temperature": {"trend_multiplier": 1.1, "trend_add_per_decade": 0.1, "shocks": [{"year": 2030, "size": 1}]},
            "sea_level": {"threshold": {"value": 0.35}, "trend_multiplier": 2, "trend_add_per_decade": 0.1,
                          "shocks": [{"year": 2030 + i, "size": 0.01} for i in range(4)],
                          "drivers": [{"from": "temperature", "coefficient": 0}] * 2}}
    assert scenarios.MAX_KNOBS == 10
    bad = client.post(f"/api/twin/{tid}/sensitivity", json={"target": "sea_level", "n_runs": 50, "scenario": many})
    assert bad.status_code == 422 and "At most 10 knobs" in bad.text, bad.text
    assert client.post(f"/api/twin/{tid}/sensitivity",
                       json={"target": "temperature", "n_runs": 50, "scenario": sc}).status_code == 422  # no threshold


def test_delete_variable_and_twin(client):
    tid = _setup(client)
    r = client.delete(f"/api/twin/{tid}/variables/sea_level")
    assert r.status_code == 200 and r.json()["variables"] == ["temperature"]
    assert client.delete(f"/api/twin/{tid}/variables/sea_level").status_code == 404
    assert client.delete(f"/api/twin/{tid}").status_code == 200
    assert client.get(f"/api/twin/{tid}").status_code == 404
    assert client.delete(f"/api/twin/{tid}").status_code == 404
