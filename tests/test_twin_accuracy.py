"""Digital-twin calibration benchmark: backtest coverage of the 5-95% band on synthetic series with a known
truth and on real recorded series (offline). The band should hold ~90% of held-out months."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.timeseries.model import MonthlySeries, Provenance, RawSeries, ValueMeta
from backend.timeseries.parsers import parse_ncei_ads_json
from backend.timeseries.resample import to_monthly
from backend.twin.engine import backtest

REC = Path(__file__).parent / "fixtures" / "recorded"
PROV = Provenance("benchmark", "x", {})
# coverage measured before the calibration changes (same seeds); no case may fall further from 0.90
BEFORE = {"ar_phi0": 0.863, "ar_phi4": 0.872, "ar_phi8": 0.805, "seasonal_var": 0.872, "trend_change": 0.731,
          "trend_change_auto": 0.731, "heavy_tails": 0.918, "gsom_prcp": 0.500, "gsom_tavg": 0.800,
          "nsidc_dec_extent": 0.700}


def _ms(time, v, units="x"):
    return MonthlySeries(time=pd.DatetimeIndex(time), value=np.asarray(v, float), units=units, provenance=PROV)


def _ar(rng, n, phi, eps):
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def synthetic(name: str, rep: int) -> MonthlySeries:
    rng = np.random.default_rng(1000 * rep + sum(map(ord, name)))
    n = 480
    t = np.arange(n) / 12
    seas = 3 * np.sin(2 * np.pi * t)
    phi, eps, trend = 0.3, rng.normal(0, 1, n), 0.02 * t
    if name.startswith("ar_phi"):
        phi = int(name[-1]) / 10
    elif name == "seasonal_var":                      # winter noise 3x summer noise
        eps = eps * (1 + 2 * (np.cos(2 * np.pi * t) > 0))
    elif name == "trend_change":                      # flat, then a strong trend after year 18
        trend = np.where(t > 18, 0.12 * (t - 18), 0.0)
    elif name == "heavy_tails":
        eps = rng.standard_t(3, n) / np.sqrt(3)
    eps = eps * np.sqrt(1 - phi ** 2)
    return _ms(pd.date_range("1985-01-01", periods=n, freq="MS"), 10 + seas + trend + _ar(rng, n, phi, eps))


def real() -> dict[str, MonthlySeries]:
    raw = (REC / "ncei_gsom_IN020040900_1981_2024.json").read_text(encoding="utf-8")
    out = {}
    for var, units in (("PRCP", "mm"), ("TAVG", "degC")):
        t, v, _ = parse_ncei_ads_json(raw, var)
        out[f"gsom_{var.lower()}"] = to_monthly(RawSeries(t, v, "monthly", PROV, ValueMeta(units=units)),
                                                start="1981-01-01", end="2024-12-31")
    sii = pd.read_csv(REC / "nsidc_N_12_extent_v4.0.csv", skipinitialspace=True)
    sii = sii[sii["extent"] > 0]                      # -9999 sentinel
    idx = pd.date_range("1978-01-01", f"{sii['year'].max()}-12-01", freq="MS")
    val = pd.Series(np.nan, idx)
    val[pd.to_datetime(sii["year"].astype(str) + "-12-01")] = sii["extent"].to_numpy()
    out["nsidc_dec_extent"] = _ms(idx, val.to_numpy(), "1e6 km2")
    return out


def coverage() -> dict[str, float]:
    res = {}
    for name in ("ar_phi0", "ar_phi4", "ar_phi8", "seasonal_var", "trend_change", "heavy_tails"):
        covs = [backtest({name: synthetic(name, r)}, holdout_years=10, n_runs=300, seed=r)["variables"][name]["band_coverage"]
                for r in range(8)]
        res[name] = float(np.mean(covs))
    # the fit_since_year="auto" knob (trend after the last PELT break) on the same trend-change series
    sc = {"trend_change": {"fit_since_year": "auto"}}
    res["trend_change_auto"] = float(np.mean([backtest({"trend_change": synthetic("trend_change", r)}, seed=r,
                                                       scenario=sc)["variables"]["trend_change"]["band_coverage"]
                                              for r in range(8)]))
    for name, ms in real().items():
        res[name] = backtest({name: ms}, holdout_years=10, n_runs=300)["variables"][name]["band_coverage"]
    return res


@pytest.fixture(scope="module")
def cov():
    return coverage()


def test_mean_coverage_is_honest(cov):
    assert 0.82 <= np.mean(list(cov.values())) <= 0.97, cov


def test_no_case_regresses(cov):
    for k, c in cov.items():
        assert abs(c - 0.90) <= abs(BEFORE[k] - 0.90) + 0.02, (k, c, BEFORE[k])


if __name__ == "__main__":
    for k, v in coverage().items():
        print(f"{k:18s} {v:.3f}")
