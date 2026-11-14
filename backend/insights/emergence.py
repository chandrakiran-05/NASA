"""Time of Emergence (ToE) — when did the trend rise out of the natural year-to-year noise?

Signal S(year) = fitted linear change since the baseline (first `baseline_years`).
Noise  N      = standard deviation of detrended *annual-mean* anomalies.
ToE_k         = first year with |S| >= k * N  (k = 1 "emerging", k = 2 "clearly emerged").

Two versions are reported:
* `fitted`   — from the linear fit (may lie in the future: then it is an extrapolation, flagged)
* `observed` — first year after which the 5-year running mean of the data stays beyond k*N
               from the baseline mean (no extrapolation).
Reference concept: Hawkins & Sutton (2012), "Time of emergence of climate signals", GRL.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def annual_means(time: pd.DatetimeIndex, y: np.ndarray, min_months: int = 9) -> pd.Series:
    s = pd.Series(np.asarray(y, float), index=time)
    g = s.groupby(time.year)
    cnt = g.count()
    m = g.mean()
    return m[cnt >= min_months]


def time_of_emergence(time: pd.DatetimeIndex, deseasonalized: np.ndarray, slope_per_year: float,
                      baseline_years: int = 10) -> dict:
    ann = annual_means(time, deseasonalized)
    if len(ann) < baseline_years + 3:
        return {"status": "too_short", "plain_language": "Record too short to estimate time of emergence."}
    yrs = ann.index.to_numpy().astype(float)
    vals = ann.to_numpy()
    coef = np.polyfit(yrs, vals, 1)
    resid = vals - np.polyval(coef, yrs)
    noise = float(np.std(resid, ddof=2))
    base_mask = yrs < yrs[0] + baseline_years
    base_center = float(yrs[base_mask].mean())
    base_mean = float(vals[base_mask].mean())
    slope = slope_per_year if math.isfinite(slope_per_year) else coef[0]
    out = {
        "method": "signal-to-noise on annual means (Hawkins & Sutton 2012 concept)",
        "baseline": [int(yrs[base_mask][0]), int(yrs[base_mask][-1])],
        "noise_sd_annual": noise,
        "signal_to_noise_now": abs(slope * (yrs[-1] - base_center)) / noise if noise > 0 else None,
    }
    for k in (1, 2):
        key = f"toe_{k}sigma"
        if noise <= 0 or slope == 0:
            out[key] = {"year": None, "projected": False}
            continue
        yr = base_center + k * noise / abs(slope)
        out[key] = {"year": int(math.ceil(yr)), "projected": yr > yrs[-1]}
        # observed: 5-yr running mean stays beyond k*noise
        rm = pd.Series(vals, index=yrs).rolling(5, center=True, min_periods=3).mean()
        beyond = (np.sign(slope) * (rm.to_numpy() - base_mean)) >= k * noise
        obs_year = None
        for i in range(len(beyond)):
            if beyond[i] and beyond[i:].all():
                obs_year = int(yrs[i])
                break
        out[key]["observed_year"] = obs_year

    t1, t2 = out.get("toe_1sigma", {}), out.get("toe_2sigma", {})
    if t2.get("year") and not t2.get("projected"):
        txt = (f"The change rose clearly above natural year-to-year variability (2× noise) around {t2['year']}"
               + (f"; the data themselves confirm it from {t2['observed_year']}." if t2.get("observed_year") else "."))
    elif t1.get("year") and not t1.get("projected"):
        txt = (f"The change started to stand out from year-to-year variability around {t1['year']}, but has not "
               f"yet reached twice the noise level (projected around {t2.get('year')} at the current rate).")
    elif t1.get("year"):
        txt = (f"The change is still hidden in year-to-year variability; at the current rate it would emerge "
               f"around {t1['year']} (an extrapolation).")
    else:
        txt = "No emergence: there is no trend to emerge."
    out["plain_language"] = txt
    out["annual"] = {"year": [int(y) for y in yrs], "value": [float(v) for v in vals]}
    return out


def record_statistics(time: pd.DatetimeIndex, deseasonalized: np.ndarray) -> dict:
    """Record-breaking test on annual means (Benestad 2003 idea).

    For an i.i.d. series of n years the expected number of record highs is H_n = sum 1/i, with
    variance sum (1/i - 1/i^2). Many more record highs than expected (or lows) signals a trend
    in a way that is easy to explain to students.
    """
    ann = annual_means(time, deseasonalized)
    v = ann.to_numpy()
    n = len(v)
    if n < 8:
        return {"status": "too_short"}
    hi = lo = 0
    hi_years, lo_years = [], []
    for i in range(n):
        if i == 0 or v[i] > v[:i].max():
            hi += 1
            hi_years.append(int(ann.index[i]))
        if i == 0 or v[i] < v[:i].min():
            lo += 1
            lo_years.append(int(ann.index[i]))
    i = np.arange(1, n + 1, dtype=float)
    expected = float(np.sum(1 / i))
    var = float(np.sum(1 / i - 1 / i ** 2))
    from scipy.stats import norm
    z_hi = (hi - expected) / math.sqrt(var)
    z_lo = (lo - expected) / math.sqrt(var)
    return {
        "n_years": n,
        "record_highs": hi, "record_high_years": hi_years,
        "record_lows": lo, "record_low_years": lo_years,
        "expected_if_no_trend": expected,
        "p_highs": float(norm.sf(z_hi)), "p_lows": float(norm.sf(z_lo)),
        "plain_language": (f"{hi} record-high years and {lo} record-low years in {n} years; "
                           f"without a trend about {expected:.1f} of each would be expected."),
    }
