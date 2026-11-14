"""F2 — Evidence Clock + cherry-pick rank.

Bundles: the trend triangle (every start x end window), the expanding-window "end-year slider",
the years-to-detect countdown (Weatherhead 1998) and the rank of the user's chosen window
among all windows of the same length.
"""
from __future__ import annotations

import math

import numpy as np

from ..analysis.deseason import deseasonalize
from ..analysis.trend import ols_trend
from ..insights.detectability import detectability
from ..insights.triangle import trend_triangle
from ..timeseries.model import MonthlySeries


def expanding_window(ms: MonthlySeries, y: np.ndarray, min_years: int = 10, alpha: float = 0.05) -> list[dict]:
    t = ms.t_years()
    years = ms.time.year.to_numpy()
    first = years[0]
    out = []
    for end in range(first + min_years - 1, years[-1] + 1):
        m = years <= end
        if np.isfinite(y[m]).sum() < 24:
            continue
        o = ols_trend(t[m], y[m], alpha)
        out.append({"end_year": int(end), "slope_per_decade": o.slope * 10,
                    "ci95_adj_per_decade": [o.ci95_adj[0] * 10, o.ci95_adj[1] * 10],
                    "p_adj": o.p_adj, "significant": o.p_adj < alpha})
    return out


def window_rank(tri: dict, start: int, end: int) -> dict | None:
    L = end - start + 1
    starts, ends, S = tri["start_years"], tri["end_years"], tri["slope_per_decade"]
    same = []
    for i, s in enumerate(starts):
        e = s + L - 1
        if e in ends:
            v = S[i][ends.index(e)]
            if v is not None:
                same.append((s, v))
    mine = next((v for s, v in same if s == start), None)
    if mine is None or len(same) < 3:
        return None
    vals = sorted(v for _, v in same)
    rank_low = 1 + sum(v < mine for v in vals)             # 1 = flattest / most negative
    pct = 100 * (rank_low - 1) / (len(vals) - 1)
    if pct <= 15:
        txt = "unusually low (flat or falling) compared with other windows of the same length"
    elif pct >= 85:
        txt = "unusually steep compared with other windows of the same length"
    else:
        txt = "typical of windows of the same length"
    return {"start": start, "end": end, "length_years": L, "slope_per_decade": mine,
            "rank_from_lowest": rank_low, "n_windows": len(vals), "percentile": pct,
            "plain_language": f"Your {L}-year window ranks {rank_low} of {len(vals)} (from the lowest slope): {txt}."}


def evidence_clock(ms: MonthlySeries, *, start: int | None = None, end: int | None = None, min_years: int = 10,
                   alpha: float = 0.05) -> dict:
    t = ms.t_years()
    y = deseasonalize(ms, "stl").deseasonalized
    o = ols_trend(t, y, alpha)
    valid_t = t[np.isfinite(y)]
    rec = float(valid_t[-1] - valid_t[0] + 1 / 12)
    start_year = ms.time[0].year + (ms.time[0].month - 1) / 12 + float(valid_t[0])   # first month WITH data
    det = detectability(o.slope, o.residuals, rec, start_year, phi=o.lag1_autocorr)
    # "can't tell" when the slope is indistinguishable from zero at the 1-sigma level
    if o.se_adj > 0 and abs(o.slope) < o.se_adj:
        det["status"] = "cant_tell"
        det["plain_language"] = ("Can't tell: the estimated slope is smaller than its own uncertainty, so no "
                                 "record length can be promised.")
    elif det.get("years_needed"):
        yrs_more = det["years_remaining"]
        det["plain_language"] = (
            "Already detectable with this record." if yrs_more <= 0 else
            f"If the current rate and noise persist, about {math.ceil(yrs_more)} more years "
            f"(≈{math.ceil(start_year + det['years_needed'])}).")
    tri = trend_triangle(ms.time, t, y, min_years=min_years, lag1=o.lag1_autocorr, alpha=alpha)
    out = {"triangle": tri, "triangle_label": "exploratory: overlapping windows are not independent tests",
           "expanding": expanding_window(ms, y, min_years, alpha), "years_to_detect": det,
           "assumptions": ["AR(1) noise", "the current linear rate continues", "90% detection probability at 5% significance"]}
    if start is not None and end is not None and "start_years" in tri:
        out["window_rank"] = window_rank(tri, start, end)
    return out
