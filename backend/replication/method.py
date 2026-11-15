"""The paper's method, step by step (Acker et al., NTRS 20090042747).

1. Least-squares line through the complete monthly series (x = month number, so the slope is per month),
   ANOVA F-test (simple regression: F = t^2, same p as the plain t-test), R^2, mean.
2. Yearly anomalies: subtract each calendar month's mean from each month, average those monthly anomalies
   per calendar year, regress the yearly anomalies on the year.
Also reported: our app's default p, which corrects for month-to-month persistence (AR(1) effective sample
size, Santer et al. 2000). The paper's F-test treats every month as independent, so its p can be smaller.
Missing months stay missing; nothing is filled.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..analysis.deseason import monthly_climatology
from ..analysis.trend import ols_trend
from ..timeseries.model import MonthlySeries, Provenance

ALPHA = 0.05
MIN_MONTHS = 24
MIN_YEARS = 4


def _mask(time: pd.DatetimeIndex, value: np.ndarray, exclude: dict | None) -> np.ndarray:
    y = np.asarray(value, float).copy()
    if exclude:
        a, b = pd.Period(exclude["start"], "M"), pd.Period(exclude["end"], "M")
        per = time.to_period("M")
        y[(per >= a) & (per <= b)] = np.nan
    return y


def _fit(x: np.ndarray, y: np.ndarray) -> dict:
    r = ols_trend(x, y)
    return {"slope": r.slope, "intercept": r.intercept, "F": r.t_stat ** 2, "p": r.p, "r2": r.r2, "n": r.n,
            "significant": r.p < ALPHA, "p_persistence_corrected": r.p_adj,
            "significant_persistence_corrected": r.p_adj < ALPHA, "lag1_autocorr": r.lag1_autocorr}


def yearly_anomalies(time: pd.DatetimeIndex, y: np.ndarray) -> pd.DataFrame:
    """Steps 1-2: monthly anomalies vs each calendar month's mean, then their mean per calendar year."""
    ms = MonthlySeries(time=time, value=y, units=None, provenance=Provenance("replication", "chl", {}))
    anom = y - monthly_climatology(ms)[time.month.to_numpy() - 1]
    df = pd.DataFrame({"year": time.year, "anom": anom}).dropna()
    g = df.groupby("year")["anom"]
    return pd.DataFrame({"anomaly": g.mean(), "n_months": g.size()})


def paper_regression(time, value, exclude: dict | None = None) -> dict:
    """Monthly OLS + ANOVA F, and the yearly-anomaly regression, on one monthly series."""
    time = pd.DatetimeIndex(time)
    y = _mask(time, value, exclude)
    n_valid = int(np.isfinite(y).sum())
    out = {"n_months": len(y), "n_valid": n_valid, "excluded": exclude,
           "period": {"start": time[0].strftime("%Y-%m"), "end": time[-1].strftime("%Y-%m")} if len(time) else None}
    if n_valid < MIN_MONTHS:
        return {**out, "status": "insufficient",
                "message": f"only {n_valid} valid months (need at least {MIN_MONTHS})"}
    x = np.arange(len(y), dtype=float)                          # month number: slope per month, as the paper
    m = _fit(x, y)
    monthly = {**m, "slope_per_month": m["slope"], "slope_per_decade": m["slope"] * 120,
               "mean": float(np.nanmean(y)), "units": "mg m-3"}
    ya = yearly_anomalies(time, y)
    yearly = None
    if len(ya) >= MIN_YEARS:
        yf = _fit(ya.index.to_numpy(float), ya["anomaly"].to_numpy())
        yearly = {**yf, "slope_per_year": yf["slope"], "slope_per_decade": yf["slope"] * 10, "n_years": len(ya)}
    fit = m["intercept"] + m["slope"] * x
    yfit = (yearly["intercept"] + yearly["slope"] * ya.index.to_numpy(float)) if yearly else None
    return {**out, "status": "ok", "monthly": monthly, "yearly": yearly,
            "series": {"time": [t.strftime("%Y-%m") for t in time],
                       "value": [None if not np.isfinite(v) else round(float(v), 5) for v in y],
                       "fit": [round(float(v), 5) for v in fit]},
            "yearly_series": {"year": [int(v) for v in ya.index], "anomaly": [round(float(v), 5) for v in ya["anomaly"]],
                              "n_months": [int(v) for v in ya["n_months"]],
                              "fit": [round(float(v), 5) for v in yfit] if yfit is not None else None}}


def agreement(published: dict, ours: dict | None) -> dict:
    """Consistent = same significance call (p < 0.05) as the paper and, where the paper's trend is significant,
    the same direction. Two non-significant slopes are not compared by sign: neither has a reliable direction."""
    if not ours or ours.get("status") != "ok":
        return {"label": "Not enough data", "same_sign": None, "same_significance": None, "within_factor_2": None,
                "plain_language": "Not enough valid months to compare with the published result."}
    m = ours["monthly"]
    same_sign = bool(np.sign(m["slope_per_month"]) == np.sign(published["slope_per_month"]))
    same_sig = bool(m["significant"] == published["significant"])
    ratio = m["slope_per_month"] / published["slope_per_month"] if published["slope_per_month"] else None
    within = bool(ratio is not None and 0.5 <= ratio <= 2.0)
    ok = same_sig and (same_sign or not published["significant"])
    why = []
    if not same_sign and published["significant"]:
        why.append("the trend direction is opposite")
    if not same_sig:
        why.append("one result is significant at p < 0.05 and the other is not")
    return {"label": "Consistent" if ok else "Differs", "same_sign": same_sign, "same_significance": same_sig,
            "both_significant": bool(m["significant"] and published["significant"]),
            "slope_ratio": ratio, "within_factor_2": within,
            "plain_language": ("Consistent with the published result: the same significance call at p < 0.05"
                               + (" and the same trend direction." if published["significant"] else
                                  " (neither trend is significant, so their directions are not compared).") if ok else
                               "Differs from the published result: " + " and ".join(why) + ".")}
