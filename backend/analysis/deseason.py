"""Seasonal-cycle removal (challenge: "some trends are not evident unless regular cycles,
such as the seasonal cycle, are removed").

* `stl`          statsmodels STL(period=12, robust=True). STL cannot take NaN, so gaps are
                 filled *only to fit the decomposition* (climatology + linear interpolation);
                 the deseasonalized output is NaN wherever the input was NaN. No value is invented.
* `climatology`  anomaly vs the mean of each calendar month (works with any gap pattern).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from ..timeseries.model import MonthlySeries


@dataclass
class Deseasonalized:
    method: str
    deseasonalized: np.ndarray       # y - seasonal (NaN where y is NaN)
    seasonal: np.ndarray
    trend_component: np.ndarray | None
    residual: np.ndarray | None
    climatology: np.ndarray          # 12 monthly means (Jan..Dec)
    seasonal_amplitude: float        # max - min of the climatology
    notes: list[str]


def monthly_climatology(ms: MonthlySeries) -> np.ndarray:
    months = ms.time.month.to_numpy() - 1
    clim = np.full(12, np.nan)
    for m in range(12):
        v = ms.value[months == m]
        v = v[np.isfinite(v)]
        if len(v):
            clim[m] = v.mean()
    return clim


def climatology_anomalies(ms: MonthlySeries) -> Deseasonalized:
    clim = monthly_climatology(ms)
    months = ms.time.month.to_numpy() - 1
    seasonal = clim[months]
    # anomalies relative to each month's mean, then add back the overall mean so units stay
    overall = np.nanmean(ms.value)
    des = ms.value - seasonal + overall
    amp = float(np.nanmax(clim) - np.nanmin(clim)) if np.isfinite(clim).any() else 0.0
    return Deseasonalized("climatology", des, seasonal - overall, None, None, clim, amp, [])


def stl_decompose(ms: MonthlySeries, robust: bool = True) -> Deseasonalized:
    y = ms.value
    notes: list[str] = []
    if ms.n < 24 or np.isfinite(y).sum() < 24:
        out = climatology_anomalies(ms)
        out.notes.append("Series shorter than 2 years: used monthly-climatology anomalies instead of STL.")
        return out
    clim = monthly_climatology(ms)
    filled = y.copy()
    gaps = ~np.isfinite(filled)
    if gaps.any():
        months = ms.time.month.to_numpy() - 1
        # anomaly interpolation keeps the seasonal shape inside gaps
        anom = pd.Series(y - clim[months]).interpolate(limit_direction="both").to_numpy()
        filled[gaps] = (anom + clim[months])[gaps]
        if not np.isfinite(filled).all():  # a calendar month never observed
            filled = pd.Series(filled).interpolate(limit_direction="both").to_numpy()
        notes.append(f"{int(gaps.sum())} missing month(s) were temporarily filled only to fit STL; "
                     "they remain missing in all outputs and tests.")
    res = STL(pd.Series(filled, index=ms.time), period=12, robust=robust).fit()
    seasonal = res.seasonal.to_numpy()
    des = y - seasonal                       # NaN where y is NaN
    trend = res.trend.to_numpy().copy()
    resid = res.resid.to_numpy().copy()
    trend[gaps] = np.nan
    resid[gaps] = np.nan
    amp = float(np.nanmax(clim) - np.nanmin(clim)) if np.isfinite(clim).any() else 0.0
    return Deseasonalized("stl", des, seasonal, trend, resid, clim, amp, notes)


def deseasonalize(ms: MonthlySeries, method: str = "stl") -> Deseasonalized:
    if method == "stl":
        return stl_decompose(ms)
    if method == "climatology":
        return climatology_anomalies(ms)
    if method == "none":
        z = np.zeros(ms.n)
        return Deseasonalized("none", ms.value.copy(), z, None, None, monthly_climatology(ms), 0.0, [])
    raise ValueError(f"unknown deseasonalization method {method!r}")
