"""Trend-break detection — "did the trend change speed or reverse?"

Optimal piecewise-linear segmentation by PELT (Killick, Fearnhead & Eckley 2012) with a
segment cost equal to the RSS of a straight-line fit, evaluated in O(1) from prefix sums.
Expected run time is linear in the series length.

Penalty: beta = c * sigma^2 * ln(n) * (1+phi)/(1-phi)
  sigma^2 robust noise variance (MAD of first differences, corrected for AR(1)),
  phi     lag-1 autocorrelation of residuals; the AR(1) inflation avoids "breaks" that are
          just persistent noise. c = 3 is BIC-like for (slope, intercept, location).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from ..analysis import kernels as K
from ..analysis.trend import mann_kendall, ols_trend, sens_slope


def _robust_sigma2(y: np.ndarray, phi: float) -> float:
    d = np.diff(y)
    mad = np.median(np.abs(d - np.median(d))) * 1.4826
    # var(diff) = 2 sigma^2 (1 - phi) for AR(1)
    return float(mad ** 2 / (2 * max(1 - phi, 0.05)))


def detect_trend_breaks(time: pd.DatetimeIndex, t_years: np.ndarray, y: np.ndarray, *,
                        min_segment_years: float = 4.0, penalty_mult: float = 3.0, max_breaks: int = 3,
                        alpha: float = 0.05) -> dict:
    m = np.isfinite(y)
    t = np.asarray(t_years, float)[m]
    v = np.asarray(y, float)[m]
    tt = time[m]
    n = len(v)
    min_size = max(int(round(min_segment_years * 12)), 12)
    if n < 2 * min_size:
        return {"status": "too_short", "breaks": [], "segments": [],
                "plain_language": f"Need at least {2 * min_size} valid months to look for trend breaks."}

    base = ols_trend(t, v, alpha)
    phi = float(min(max(base.lag1_autocorr, 0.0), 0.9))
    s2 = _robust_sigma2(v, phi)
    infl = (1 + phi) / (1 - phi)
    pen = penalty_mult * s2 * math.log(n) * infl
    cs = K.prefix_sums(t, v)

    cps = K.pelt_linear(cs, pen, min_size)
    # cap the number of breaks: raise the penalty until satisfied
    tries = 0
    while len(cps) > max_breaks and tries < 20:
        pen *= 1.5
        cps = K.pelt_linear(cs, pen, min_size)
        tries += 1

    bounds = [0, *[int(c) for c in cps], n]
    segments = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        seg_t, seg_y = t[a:b], v[a:b]
        o = ols_trend(seg_t, seg_y, alpha)
        sen = sens_slope(seg_t, seg_y, alpha)
        try:
            mk = mann_kendall(seg_t, seg_y, alpha, "ess_ar1")
            mk_p = mk.p
        except ValueError:
            mk_p = None
        segments.append({
            "start": tt[a].strftime("%Y-%m"), "end": tt[b - 1].strftime("%Y-%m"), "n_months": int(b - a),
            "slope_per_decade": o.slope * 10, "ci95_adj_per_decade": [o.ci95_adj[0] * 10, o.ci95_adj[1] * 10],
            "p_adj": o.p_adj, "mk_p": mk_p, "sen_slope_per_decade": sen.slope * 10,
            "se_adj": o.se_adj, "significant": bool(o.p_adj < alpha and (mk_p is None or mk_p < alpha)),
        })

    # information criterion comparison against a single straight line
    rss1 = float(np.sum((v - (base.intercept + base.slope * t)) ** 2))
    rssk = sum(K._seg_cost(cs, a, b) for a, b in zip(bounds[:-1], bounds[1:]))
    k_params_1, k_params_k = 2, 3 * (len(bounds) - 1) - 1
    n_eff = base.n_eff
    bic1 = n_eff * math.log(rss1 / n) + k_params_1 * math.log(n_eff)
    bick = n_eff * math.log(max(rssk, 1e-300) / n) + k_params_k * math.log(n_eff)

    breaks = []
    for i, c in enumerate(cps):
        s0, s1 = segments[i], segments[i + 1]
        diff = (s1["slope_per_decade"] - s0["slope_per_decade"])
        se = math.hypot(s0["se_adj"] * 10, s1["se_adj"] * 10)
        z = diff / se if se > 0 else 0.0
        p = float(2 * stats.norm.sf(abs(z)))
        kind = ("reversal" if np.sign(s0["slope_per_decade"]) != np.sign(s1["slope_per_decade"])
                and (s0["significant"] or s1["significant"]) else
                ("acceleration" if abs(s1["slope_per_decade"]) > abs(s0["slope_per_decade"]) else "slowdown"))
        breaks.append({"date": tt[int(c)].strftime("%Y-%m"), "index": int(np.flatnonzero(m)[int(c)]),
                       "slope_change_per_decade": diff, "p_slope_change": p, "kind": kind})

    if not breaks:
        txt = "No break in the trend: a single straight line describes the record best."
    else:
        parts = [f"{b['kind']} around {b['date']}" for b in breaks]
        txt = ("The trend changed: " + "; ".join(parts) + ". Segment rates: " +
               ", ".join(f"{s['start'][:4]}–{s['end'][:4]}: {s['slope_per_decade']:+.3g}/decade" for s in segments) + ".")
        if bick >= bic1:
            txt += " (Weak evidence: the single-line model has a similar or better BIC.)"
    for s in segments:
        s.pop("se_adj", None)
    return {
        "method": "PELT, piecewise-linear cost, AR(1)-inflated BIC-type penalty",
        "penalty": pen, "min_segment_months": min_size,
        "breaks": breaks, "segments": segments,
        "bic_single_line": bic1, "bic_segmented": bick,
        "segmented_preferred": bool(breaks) and bick < bic1,
        "plain_language": txt,
    }
