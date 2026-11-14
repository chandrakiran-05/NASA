import math
import warnings

import numpy as np
import pandas as pd
import pytest

from backend.analysis.engine import analyze_series
from backend.insights.changepoint import detect_trend_breaks
from backend.insights.compare import compare_regions
from backend.insights.cube import cube_trends
from backend.insights.detectability import detectability
from backend.insights.drivers import driver_analysis
from backend.insights.emergence import record_statistics, time_of_emergence
from backend.insights.engine import run_insights
from backend.insights.forecast import forecast_ensemble
from backend.insights.triangle import trend_triangle
from backend.timeseries.model import MonthlySeries, Provenance

warnings.filterwarnings("ignore")
IDX = pd.date_range("2000-01-01", periods=300, freq="MS")
T = np.arange(300) / 12


def ar(phi, sd, seed, n=300):
    rng = np.random.default_rng(seed)
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = phi * e[i - 1] + rng.normal(0, sd)
    return e


def ms_of(y, label="x", units="degC"):
    return MonthlySeries(IDX[:len(y)], np.asarray(y, float), units, Provenance("test", "x", {}), label=label)


def test_detectability_formula_matches_weatherhead():
    resid = ar(0.5, 1.0, 0)
    sigma = np.std(resid[np.isfinite(resid)], ddof=1)
    phi = 0.5
    d = detectability(0.05, resid, 10.0, 2000.0, phi=phi)
    expected = ((3.3 * sigma / 0.05) * math.sqrt((1 + phi) / (1 - phi))) ** (2 / 3)
    assert d["years_needed"] == pytest.approx(expected)
    lo, hi = d["years_needed_95ci"]
    assert lo < expected < hi
    # bigger trends need fewer years
    assert detectability(0.2, resid, 10, 2000, phi=phi)["years_needed"] < expected


def test_change_points_no_false_alarms_and_detects_reversal():
    fp = sum(len(detect_trend_breaks(IDX, T, 0.02 * T + ar(0.5, 0.4, s))["breaks"]) for s in range(20))
    assert fp <= 1
    hits = 0
    for s in range(20):
        y = np.where(T < 12, 0.1 * T, 1.2 - 0.1 * (T - 12)) + ar(0.5, 0.4, 100 + s)
        r = detect_trend_breaks(IDX, T, y)
        if r["breaks"] and abs(int(r["breaks"][0]["date"][:4]) - 2012) <= 4:
            hits += 1
    assert hits >= 17


def test_trend_triangle_consistent_with_direct_ols():
    from backend.analysis.trend import ols_trend
    y = 0.03 * T + ar(0.3, 0.3, 7)
    tri = trend_triangle(IDX, T, y, min_years=10)
    i = tri["start_years"].index(2005)
    j = tri["end_years"].index(2019)
    m = (IDX.year >= 2005) & (IDX.year <= 2019)
    o = ols_trend(T[m], y[m])
    assert tri["slope_per_decade"][i][j] == pytest.approx(o.slope * 10, rel=1e-9)
    assert tri["robustness"] in ("robust", "mostly_robust")


def test_forecast_intervals_and_weights():
    y = 15 + 6 * np.sin(2 * np.pi * IDX.month.to_numpy() / 12) + 0.04 * T + ar(0.4, 0.4, 3)
    f = forecast_ensemble(IDX, y, horizon=36)
    fc = f["forecast"]
    assert len(fc["mean"]) == 36
    assert all(lo <= m <= hi for lo, m, hi in zip(fc["lo95"], fc["mean"], fc["hi95"]))
    assert all(a <= b for a, b in zip(np.subtract(fc["hi80"], fc["lo80"]), np.subtract(fc["hi95"], fc["lo95"])))
    assert abs(sum(f["weights"].values()) - 1) < 1e-9
    assert "not a physical climate projection" in f["disclaimer"]


def test_emergence_and_records():
    y = 0.05 * T + ar(0.2, 0.3, 9)
    e = time_of_emergence(IDX, y, 0.05)
    assert e["toe_1sigma"]["year"] <= e["toe_2sigma"]["year"]
    r = record_statistics(IDX, y)
    assert r["record_highs"] > r["expected_if_no_trend"]


def test_compare_detects_opposite_trends_with_fdr():
    a = analyze_series(ms_of(10 + 0.06 * T + ar(0.3, 0.3, 1), "A"), include_series=False)
    b = analyze_series(ms_of(10 - 0.06 * T + ar(0.3, 0.3, 2), "B"), include_series=False)
    c = analyze_series(ms_of(10 + ar(0.3, 0.3, 3), "C"), include_series=False)
    out = compare_regions([a, b, c])
    assert out["divergent"]
    names = {r["name"]: r for r in out["regions"]}
    assert names["A"]["significant_fdr"] and names["B"]["significant_fdr"]
    assert all(r["p_fdr"] >= r["p_raw"] for r in out["regions"])


def test_drivers_recovers_lag_and_share():
    drv = 100 + 20 * np.sin(2 * np.pi * IDX.month.to_numpy() / 12) + ar(0.3, 5, 4) + 0.5 * T
    lagged = np.roll(drv, 2)
    tgt = 0.5 + 0.004 * (lagged - 100) + ar(0.3, 0.01, 5)
    out = driver_analysis(ms_of(tgt, "NDVI", "1"), [ms_of(drv, "Rain", "mm")], max_lag=4)
    d = out["drivers"][0]
    assert d["best_lag_months"] == 2
    assert d["significant_fdr"]
    assert 0.6 < d["trend_share"] < 1.4
    assert "not proof" in out["plain_language"]


def test_cube_mixed_trends():
    nt, ny, nx = 240, 12, 16
    lat = np.linspace(10, 20, ny)
    lon = np.linspace(70, 85, nx)
    rng = np.random.default_rng(0)
    cube = rng.normal(0, 1, (nt, ny, nx)) + (np.arange(nt) / 12)[:, None, None] * np.where(lon < 77.5, 0.1, -0.1)
    cube[:, :2, :2] = np.nan
    out = cube_trends(cube, (np.arange(nt) % 12) + 1, lat, lon)
    assert 0.35 < out["area_fraction_rising"] < 0.65
    assert 0.35 < out["area_fraction_falling"] < 0.65
    assert out["slope_per_decade"][0][0] is None
    assert "Mixed picture" in out["plain_language"]


def test_run_insights_all_and_tei_bounds():
    y = 20 + 5 * np.sin(2 * np.pi * IDX.month.to_numpy() / 12) + 0.04 * T + ar(0.4, 0.4, 8)
    out = run_insights(ms_of(y, "Temp"))
    for k in ("detectability", "emergence", "records", "breaks", "triangle", "forecast"):
        assert "error" not in out[k], (k, out[k])
    tei = out["trend_evidence_index"]
    assert 0 <= tei["score"] <= 100
    flat = run_insights(ms_of(20 + 5 * np.sin(2 * np.pi * IDX.month.to_numpy() / 12) + ar(0.4, 0.4, 9), "Flat"))
    assert flat["trend_evidence_index"]["score"] < tei["score"]
