"""Digital twin mode: direct upload (no verification), what-if simulation, thresholds, coupling."""
import numpy as np
import pandas as pd

IDX = pd.date_range("1995-01-01", periods=360, freq="MS")
T = np.arange(360) / 12


def _twin(client):
    r = client.post("/api/twin", json={"name": "Coastal city", "description": "test"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _data(client, tid):
    rng = np.random.default_rng(0)
    temp = 15 + 0.03 * T + 5 * np.sin(2 * np.pi * T) + rng.normal(0, 0.3, 360)
    sea = 0.004 * T + rng.normal(0, 0.02, 360)
    body = {"source": "chatbot team", "variables": [
        {"name": "temperature", "units": "°C", "time": [str(d.date()) for d in IDX], "value": temp.tolist()},
        {"name": "sea_level", "units": "m", "time": [str(d.date()) for d in IDX], "value": sea.tolist()}]}
    r = client.post(f"/api/twin/{tid}/data", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_is_direct_and_separate_from_verification(client):
    tid = _twin(client)
    twin = _data(client, tid)
    assert [v["name"] for v in twin["variables"]] == ["temperature", "sea_level"]
    got = client.get(f"/api/twin/{tid}").json()
    b = got["variables"][0]["baseline"]
    assert abs(b["slope_per_decade"] - 0.3) < 0.05 and b["units"] == "°C"
    assert "verdict" not in str(got) and "court" not in str(got)
    assert any(t["id"] == tid for t in client.get("/api/twin").json()["twins"])
    # CSV path: date column + one column per variable; re-upload of a name replaces it
    csv = "date,sea_level\n" + "\n".join(f"{d.date()},{0.001 * i}" for i, d in enumerate(IDX))
    r = client.post(f"/api/twin/{tid}/data-csv", files={"file": ("x.csv", csv, "text/csv")})
    assert r.status_code == 200 and [v["name"] for v in r.json()["variables"]] == ["temperature", "sea_level"]


def test_simulation_bands_threshold_coupling_and_reproducibility(client):
    tid = _twin(client)
    _data(client, tid)
    base = {"horizon_years": 50, "n_runs": 300, "seed": 7,
            "scenario": {"sea_level": {"threshold": {"value": 0.5, "direction": "above"}}}}
    a = client.post(f"/api/twin/{tid}/simulate", json=base).json()
    assert a == client.post(f"/api/twin/{tid}/simulate", json=base).json()            # same seed, same world
    sl = a["variables"]["sea_level"]
    assert len(sl["time"]) == 600 and sl["label"] == "simulated" and "not observations" in a["disclaimer"]
    assert all(x <= y <= z for x, y, z in zip(sl["p05"], sl["p50"], sl["p95"]))
    # baseline ~0.4 mm/month -> ~0.36 m by 2075: threshold 0.5 m rarely crossed
    p_base = sl["threshold"]["probability_by_end"]
    hot = {**base, "scenario": {"temperature": {"trend_add_per_decade": 1.0},
                                "sea_level": {"drivers": [{"from": "temperature", "coefficient": 0.1}],
                                              "threshold": {"value": 0.5, "direction": "above"}}}}
    b = client.post(f"/api/twin/{tid}/simulate", json=hot).json()["variables"]["sea_level"]
    assert b["threshold"]["probability_by_end"] > p_base + 0.5 and b["threshold"]["median_first_crossing"]
    shock = {**base, "scenario": {"sea_level": {"shocks": [{"year": 2040, "size": 1.0}]}}}
    c = client.post(f"/api/twin/{tid}/simulate", json=shock).json()["variables"]["sea_level"]
    k = c["time"].index("2040-01")
    assert c["p50"][k] - c["p50"][k - 1] > 0.9


def test_twin_rejects_bad_input(client):
    tid = _twin(client)
    _data(client, tid)
    bad_driver = {"scenario": {"temperature": {"drivers": [{"from": "sea_level", "coefficient": 1}]}}}
    assert client.post(f"/api/twin/{tid}/simulate", json=bad_driver).status_code == 422      # driver must come first
    assert client.post(f"/api/twin/{tid}/simulate", json={"scenario": {"nope": {}}}).status_code == 422
    assert client.get("/api/twin/..%5C..%5Cetc").status_code == 404
    assert client.get("/api/twin/t_000000000000").status_code == 404
    short = {"variables": [{"name": "x", "time": ["2001-01", "2001-02"], "value": [1, 2]}]}
    empty = _twin(client)
    client.post(f"/api/twin/{empty}/data", json=short)
    assert client.post(f"/api/twin/{empty}/simulate", json={}).status_code == 422             # < 24 months


def test_judged_upgrades(client):
    tid = _twin(client)
    n_before = len(client.get("/api/series").json()["series"])
    _data(client, tid)
    # B1: twin data never reaches the shared verified store
    assert len(client.get("/api/series").json()["series"]) == n_before
    assert "time" not in client.get("/api/twin").json()["twins"][0]["variables"][0]
    # A4: crossing curve, one entry per year, never decreasing, ends at probability_by_end
    th = {"threshold": {"value": 0.3, "direction": "above"}}
    sl = client.post(f"/api/twin/{tid}/simulate", json={"horizon_years": 40, "n_runs": 200,
                                                         "scenario": {"sea_level": th}}).json()["variables"]["sea_level"]
    cur = [c["p"] for c in sl["threshold"]["probability_by_year"]]
    assert len(cur) == 40 and cur == sorted(cur) and cur[-1] == sl["threshold"]["probability_by_end"]
    # A1: same noise; empty knobs give zero difference, +1/decade gives about +1 after 10 years
    body = {"horizon_years": 20, "n_runs": 200, "compare_to_baseline": True, "scenario": {"temperature": {}}}
    r = client.post(f"/api/twin/{tid}/simulate", json=body).json()["variables"]["temperature"]
    assert set(r["delta_p50"]) == {0.0} and r["reference"]["label"].startswith("simulated")
    body["scenario"] = {"temperature": {"trend_add_per_decade": 1.0}}
    r = client.post(f"/api/twin/{tid}/simulate", json=body).json()["variables"]["temperature"]
    assert abs(r["delta_p50"][120] - 1.0) < 0.05
    # B2: one-way import of a main-mode series
    sid = client.post("/api/timeseries/upload", json={"time": [str(d.date()) for d in IDX],
                                                       "value": (0.01 * T).tolist(), "units": "m"}).json()["series_id"]
    tw = client.post(f"/api/twin/{tid}/import", json={"series_id": sid, "name": "official"}).json()
    assert tw["variables"][-1]["source"].startswith(f"copy of {sid}")
    assert client.get(f"/api/timeseries/{sid}").status_code == 200


def test_annual_data_runs_on_a_yearly_grid(client):
    tid = _twin(client)
    rng = np.random.default_rng(1)
    e = np.zeros(40)
    for i in range(1, 40):
        e[i] = 0.6 * e[i - 1] + rng.normal(0, 1)
    body = {"variables": [{"name": "yearly", "time": [str(1985 + i) for i in range(40)], "value": (0.05 * np.arange(40) + e).tolist()}]}
    client.post(f"/api/twin/{tid}/data", json=body)
    b = client.get(f"/api/twin/{tid}").json()["variables"][0]["baseline"]
    assert b["frequency"] == "annual" and b["lag1_autocorr"] > 0.3
    r = client.post(f"/api/twin/{tid}/simulate", json={"horizon_years": 25, "n_runs": 100}).json()["variables"]["yearly"]
    assert len(r["time"]) == 25 and all(t.endswith("-01") for t in r["time"])
