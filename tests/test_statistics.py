"""Statistical correctness: every test is validated against an independent reference
implementation (pymannkendall, scipy, statsmodels) on hundreds of random series."""
import warnings

import numpy as np
import pandas as pd
import pymannkendall as pmk
import pytest
from scipy import stats

from backend.analysis import kernels as K
from backend.analysis.engine import analyze_series
from backend.analysis.trend import mann_kendall, ols_trend, seasonal_mann_kendall, sens_slope
from backend.core.errors import InsufficientData
from backend.timeseries.model import MonthlySeries, Provenance

warnings.filterwarnings("ignore", category=RuntimeWarning)


def ar1(n, phi, rng, sd=1.0):
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = phi * e[i - 1] + rng.normal(0, sd)
    return e


def series_bank(n_series=120, seed=0):
    rng = np.random.default_rng(seed)
    for k in range(n_series):
        n = int(rng.integers(30, 360))
        y = 0.003 * np.arange(n) * rng.choice([-1, 0, 1]) + ar1(n, rng.uniform(0, 0.8), rng)
        if k % 3 == 0:
            y = np.round(y, 1)        # ties
        yield y


def test_mk_s_fenwick_equals_bruteforce():
    rng = np.random.default_rng(1)
    for _ in range(200):
        x = np.round(rng.normal(size=int(rng.integers(2, 300))), int(rng.integers(0, 3)))
        assert K.mk_s(x) == K.mk_s_bruteforce(x)


@pytest.mark.parametrize("variant,ref", [
    ("original", pmk.original_test), ("hamed_rao", pmk.hamed_rao_modification_test),
    ("yue_wang", pmk.yue_wang_modification_test)])
def test_mann_kendall_matches_pymannkendall(variant, ref):
    for y in series_bank():
        r = ref(y)
        m = mann_kendall(np.arange(len(y)) / 12, y, variant=variant)
        assert m.s == r.s
        if np.isfinite(r.p):
            assert m.p == pytest.approx(r.p, abs=1e-12)
            assert m.trend == r.trend


def test_tfpw_matches_pymannkendall_closely():
    for y in series_bank(60, seed=3):
        r = pmk.trend_free_pre_whitening_modification_test(y)
        m = mann_kendall(np.arange(len(y)) / 12, y, variant="tfpw")
        assert m.p == pytest.approx(r.p, abs=1e-3)


def test_sen_slope_and_ci_match_scipy():
    for y in series_bank():
        t = np.arange(len(y)) / 12
        ts = stats.theilslopes(y, t, 0.95)
        s = sens_slope(t, y)
        assert s.slope == pytest.approx(ts.slope, abs=1e-12)
        assert s.ci95[0] == pytest.approx(ts.low_slope, abs=1e-12)
        assert s.ci95[1] == pytest.approx(ts.high_slope, abs=1e-12)


def test_seasonal_mk_matches_pymannkendall():
    for y in series_bank():
        n = (len(y) // 12) * 12
        if n < 36:
            continue
        yy = y[:n]
        r = pmk.seasonal_test(yy, period=12)
        m = seasonal_mann_kendall(np.arange(n) // 12, np.arange(n) % 12, yy, 12)
        assert m.s == r.s
        assert m.p == pytest.approx(r.p, abs=1e-12)
        assert m.sen_slope == pytest.approx(r.slope, abs=1e-12)


def test_ols_matches_scipy_and_ar1_correction_is_conservative():
    rng = np.random.default_rng(5)
    t = np.arange(240) / 12
    y = 0.05 * t + ar1(240, 0.6, rng)
    lr = stats.linregress(t, y)
    o = ols_trend(t, y)
    assert o.slope == pytest.approx(lr.slope)
    assert o.p == pytest.approx(lr.pvalue)
    assert o.se == pytest.approx(lr.stderr)
    assert o.lag1_autocorr > 0.4
    assert o.n_eff < 240 * 0.5
    assert o.p_adj > o.p                         # stricter after correcting for persistence


@pytest.mark.parametrize("n,phi", [(120, 0.0), (120, 0.5), (240, 0.7), (360, 0.85)])
def test_default_tests_are_calibrated_under_persistence(n, phi):
    """Under H0 with AR(1) noise the tests used by the verdict (OLS AR(1)-adjusted and MK ess_ar1)
    must keep the false-positive rate near 5%, while naive OLS / original MK do not."""
    rng = np.random.default_rng(int(n * 10 + phi * 100))
    t = np.arange(n) / 12
    trials = 300
    naive = adj = mk = 0
    for _ in range(trials):
        y = ar1(n, phi, rng)
        o = ols_trend(t, y)
        naive += o.p < 0.05
        adj += o.p_adj < 0.05
        mk += mann_kendall(t, y, variant="ess_ar1").p < 0.05
    assert adj / trials < 0.11
    assert mk / trials < 0.11
    if phi >= 0.5:
        assert naive / trials > 0.15


def test_pymannkendall_default_yue_wang_is_liberal_documented():
    """Documents WHY the API does not auto-select yue_wang: with all lags it rejects ~50% under H0."""
    rng = np.random.default_rng(99)
    t = np.arange(240) / 12
    rate = np.mean([mann_kendall(t, rng.normal(size=240), variant="yue_wang").p < 0.05 for _ in range(150)])
    assert rate > 0.3


def test_gaps_are_never_filled_and_engine_runs():
    rng = np.random.default_rng(2)
    idx = pd.date_range("2001-01-01", periods=288, freq="MS")
    y = 20 + 5 * np.sin(2 * np.pi * idx.month.to_numpy() / 12) + 0.03 * np.arange(288) / 12 + ar1(288, 0.3, rng, 0.3)
    y[[3, 4, 50, 51, 52, 200]] = np.nan
    ms = MonthlySeries(idx, y, "degC", Provenance("test", "x", {}), label="Test")
    r = analyze_series(ms)
    des = np.array(r["chart"]["deseasonalized"], dtype=float)
    assert np.isnan(des[[3, 4, 50, 51, 52, 200]]).all()
    assert r["period"]["n_valid"] == 282
    assert r["verdict"]["direction"] == "rising"
    assert any("temporarily filled only to fit STL" in n for n in r["verdict"]["notes"])


def test_engine_refuses_tiny_series():
    idx = pd.date_range("2020-01-01", periods=18, freq="MS")
    ms = MonthlySeries(idx, np.arange(18.0), "x", Provenance("t", "x", {}))
    with pytest.raises(InsufficientData):
        analyze_series(ms)


def test_kernels_speed_large_n():
    import time
    x = np.random.default_rng(0).normal(size=200_000)
    t0 = time.perf_counter()
    K.mk_s(x)
    assert time.perf_counter() - t0 < 1.0     # O(n log n); brute force would take minutes
