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
