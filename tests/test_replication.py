"""Replication of the SeaWiFS river-outflow paper (Acker et al., NTRS 20090042747)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.replication.method import _fit, agreement, paper_regression, yearly_anomalies
from backend.replication.paper import BY_ID, EXCLUSIONS, RIVERS
from backend.timeseries.model import MonthlySeries, Provenance
from tests.conftest import wait_job


def test_fit_matches_hand_computed_anova():
    # x = 0..3, y = 1,3,2,4: Sxx = 5, Sxy = 4 -> b = 0.8; SSR = 3.2, TSS = 5 -> R2 = 0.64; F = 3.2 / (1.8/2)
    r = _fit(np.arange(4.0), np.array([1.0, 3.0, 2.0, 4.0]))
    assert r["slope"] == pytest.approx(0.8)
    assert r["r2"] == pytest.approx(0.64)
    assert r["F"] == pytest.approx(3.2 / 0.9)
    assert r["p"] == pytest.approx(0.2)             # F(1,2) = 32/9 -> p = 0.2 exactly
    assert not r["significant"]


def _series(years=4, start="2000-01"):
    t = pd.date_range(start, periods=12 * years, freq="MS")
    season = np.sin(2 * np.pi * (t.month.to_numpy() - 1) / 12)
    y = 1.0 + 0.1 * (t.year.to_numpy() - t.year[0]) + season
    return t, y


def test_yearly_anomalies_steps_by_hand():
    t, y = _series()
    y[5] = np.nan                                     # a missing month stays missing
    ya = yearly_anomalies(t, y)
    # month means include 0.1*k averaged over 4 years (0.15), except June (3 years left: mean of 0.1, 0.2, 0.3)
    assert ya["n_months"].tolist() == [11, 12, 12, 12]
    assert ya.loc[2001, "anomaly"] == pytest.approx(-0.05 + (0.15 - 0.2) / 12)
    out = paper_regression(t, y)
    assert out["status"] == "ok" and out["n_valid"] == 47
    assert out["monthly"]["slope_per_decade"] == pytest.approx(out["monthly"]["slope_per_month"] * 120)
    assert out["yearly"]["n_years"] == 4 and out["yearly"]["slope_per_year"] > 0
    assert out["series"]["value"][5] is None and len(out["series"]["fit"]) == 48
    assert out["monthly"]["p_persistence_corrected"] >= out["monthly"]["p"]


def test_exact_yearly_regression():
    t, y = _series()
    out = paper_regression(t, y)
    assert out["yearly_series"]["anomaly"] == pytest.approx([-0.15, -0.05, 0.05, 0.15])
    assert out["yearly"]["slope_per_year"] == pytest.approx(0.1)
    assert out["yearly"]["r2"] == pytest.approx(1.0)


def test_exclusion_window_masks_months():
    t, y = _series(years=3, start="1999-01")
    y = y.copy()
    y[(t >= "2000-10-01") & (t <= "2000-12-01")] = 50.0      # flood spike
    raw = paper_regression(t, y)
    ex = paper_regression(t, y, exclude=EXCLUSIONS["po"])
    assert ex["n_valid"] == raw["n_valid"] - 3
    assert ex["monthly"]["mean"] < raw["monthly"]["mean"]
    assert all(ex["series"]["value"][i] is None for i in (21, 22, 23))


def test_insufficient_data():
    t, y = _series(years=2)
    y[:10] = np.nan
    assert paper_regression(t, y)["status"] == "insufficient"
    assert agreement(BY_ID["po"]["published"], None)["label"] == "Not enough data"


def test_table_integrity():
    assert len(RIVERS) == 10
    for r in RIVERS:
        b = r["box"]
        assert b["north"] - b["south"] == pytest.approx(0.5) and b["east"] - b["west"] == pytest.approx(0.5)
        assert r["published"]["significant"] == (r["published"]["p"] < 0.05)
    sig = {r["id"] for r in RIVERS if r["published"]["significant"]}
    assert sig == {"eel", "ganges", "mississippi_east", "mississippi_west"}
    assert BY_ID["pearl"]["published"]["slope_per_month"] > 0


def test_agreement_labels():
    pub = BY_ID["mississippi_west"]["published"]
    mk = lambda b, p: {"status": "ok", "monthly": {"slope_per_month": b, "significant": p < 0.05}}
    assert agreement(pub, mk(-0.004, 0.01))["label"] == "Consistent"
    assert agreement(pub, mk(0.004, 0.01))["label"] == "Differs"
    assert agreement(pub, mk(-0.004, 0.5))["label"] == "Differs"
    flat = BY_ID["orinoco"]["published"]                                   # not significant in the paper
    assert agreement(flat, mk(0.0001, 0.9))["label"] == "Consistent"          # direction of a null slope not compared
    assert agreement(flat, mk(0.0013, 0.002))["label"] == "Differs"


def test_endpoint_with_stubbed_series(client):
    st = client.app.state.etd
    calls = []

    async def fake_build(variable_id, region, start, end, **kw):
        calls.append((variable_id, region.bbox, start, end))
        if variable_id == "seawifs_chlorophyll" and region.bbox[0] == 117.5:     # Pearl: SeaWiFS "down"
            raise RuntimeError("ERDDAP down")
        t = pd.date_range(start, end, freq="MS")
        y = 0.5 - 0.001 * np.arange(len(t)) + 0.05 * np.sin(np.arange(len(t)))
        sid = f"s_{variable_id}_{region.bbox[0]}_{start.year}"
        st.store.save(MonthlySeries(t, y, "mg m-3", Provenance("erddap", "chl", region.as_dict())),
                      series_id=sid, request_hash=sid, region=region.as_dict())
        return {"series_id": sid}

    st.ts.build_series = fake_build
    empty = client.get("/api/replication/seawifs").json()
    assert len(empty["rivers"]) == 10 and empty["rivers"][0]["replication"] is None and not empty["cached"]

    r = client.post("/api/replication/seawifs", json={"rivers": ["po", "pearl"]})
    assert r.status_code == 202
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done", j
    rows = {x["id"]: x for x in j["result"]["rivers"]}
    po, pearl = rows["po"], rows["pearl"]
    assert po["replication"]["variable"] == "seawifs_chlorophyll" and not po["replication"]["substitute"]
    assert po["replication"]["period"] == {"start": "1998-01", "end": "2007-12"}
    assert pearl["replication"]["substitute"] is True and pearl["replication"]["variable"] == "modis_chlorophyll"
    assert pearl["replication"]["period"]["start"] == "2002-07"
    assert pearl["agreement"]["label"] == "Differs"                       # stub falls, paper rises
    assert po["replication"]["variant"]["n_valid"] == po["replication"]["n_valid"] - 3
    assert po["extension"]["period"]["start"] == "2002-07"
    assert rows["amazon"]["agreement"]["label"] == "Not enough data"
    assert "consistent with the published result for" in j["result"]["summary"]

    cached = client.get("/api/replication/seawifs").json()                 # cached, instant
    assert cached["cached"] and cached["rivers"][-1]["replication"]["n_valid"] > 0
    bad = client.post("/api/replication/seawifs", json={"rivers": ["nile"]})
    assert bad.status_code == 400 or bad.status_code == 422
