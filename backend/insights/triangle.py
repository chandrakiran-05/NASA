"""Trend-stability triangle — "does the answer depend on which years I picked?"

Computes the OLS trend (and AR(1)-adjusted significance) for EVERY start-year/end-year window
of at least `min_years`, in O(1) per window from prefix sums. Students can see at a glance
whether a trend is robust or an artefact of cherry-picked start/end dates
(cf. "trend triangles", Liebmann et al. 2010, BAMS).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats


def trend_triangle(time: pd.DatetimeIndex, t_years: np.ndarray, y: np.ndarray, *, min_years: int = 10,
                   lag1: float = 0.0, alpha: float = 0.05, min_coverage: float = 0.7) -> dict:
    v = np.asarray(y, float)
    t = np.asarray(t_years, float)
    m = np.isfinite(v)
    tv = np.where(m, t, 0.0)
    yv = np.where(m, v, 0.0)
    c = np.zeros((6, len(v) + 1))
    c[0, 1:] = np.cumsum(m)
    c[1, 1:] = np.cumsum(tv)
    c[2, 1:] = np.cumsum(tv * tv)
    c[3, 1:] = np.cumsum(yv)
    c[4, 1:] = np.cumsum(yv * yv)
    c[5, 1:] = np.cumsum(tv * yv)

    years = time.year.to_numpy()
    uniq = np.unique(years)
    first_idx = {yr: int(np.argmax(years == yr)) for yr in uniq}
    last_idx = {yr: int(len(years) - 1 - np.argmax(years[::-1] == yr)) for yr in uniq}
    r = min(max(lag1, 0.0), 0.95)
    infl = (1 - r) / (1 + r)

    starts, ends = [], []
    slope_mat, p_mat = [], []
    cells = []
    for ys in uniq:
        row_s, row_p = [], []
        for ye in uniq:
            if ye - ys + 1 < min_years:
                row_s.append(None)
                row_p.append(None)
                continue
            a, b = first_idx[ys], last_idx[ye] + 1
            n = c[0, b] - c[0, a]
            if n < min_coverage * (b - a) or n < 24:
                row_s.append(None)
                row_p.append(None)
                continue
            st, stt, sy, syy, sty = (c[k, b] - c[k, a] for k in range(1, 6))
            sxx = stt - st * st / n
            sxy = sty - st * sy / n
            syy_c = syy - sy * sy / n
            slope = sxy / sxx
            rss = max(syy_c - slope * sxy, 0.0)
            neff = max(n * infl, 3.0)
            se = math.sqrt(rss / (n - 2) / sxx) * math.sqrt((n - 2) / max(neff - 2, 1.0))
            p = float(2 * stats.t.sf(abs(slope / se), max(neff - 2, 1.0))) if se > 0 else 0.0
            row_s.append(slope * 10.0)
            row_p.append(p)
            cells.append((int(ys), int(ye), slope * 10.0, p))
        starts.append(int(ys))
        slope_mat.append(row_s)
        p_mat.append(row_p)
    ends = [int(y) for y in uniq]

    if not cells:
        return {"status": "too_short", "plain_language": f"Need at least {min_years} years for the trend triangle."}

    arr = np.array([(cl[2], cl[3]) for cl in cells])
    full = next((cl for cl in cells if cl[0] == starts[0] and cl[1] == ends[-1]), cells[-1])
    sign_full = np.sign(full[2])
    same_sign = float(np.mean(np.sign(arr[:, 0]) == sign_full))
    sig_same = float(np.mean((np.sign(arr[:, 0]) == sign_full) & (arr[:, 1] < alpha)))
    sig_opp = float(np.mean((np.sign(arr[:, 0]) != sign_full) & (arr[:, 1] < alpha)))
    recent = {}
    for L in (10, 20, 30):
        cl = next((x for x in cells if x[1] == ends[-1] and x[1] - x[0] + 1 == L), None)
        if cl:
            recent[f"last_{L}_years"] = {"start": cl[0], "end": cl[1], "slope_per_decade": cl[2], "p": cl[3]}
    if same_sign > 0.9 and sig_opp == 0:
        robust = "robust"
        txt = (f"Robust: {same_sign * 100:.0f}% of all {min_years}+ year windows show the same direction, "
               f"and {sig_same * 100:.0f}% are significant.")
    elif same_sign > 0.7:
        robust = "mostly_robust"
        txt = (f"Mostly robust: {same_sign * 100:.0f}% of windows agree on the direction, but the size or "
               "significance depends on the chosen years.")
    else:
        robust = "fragile"
        txt = (f"Fragile: only {same_sign * 100:.0f}% of windows agree on the direction — the result depends "
               "strongly on which start and end years are chosen.")
    return {
        "min_years": min_years,
        "start_years": starts,
        "end_years": ends,
        "slope_per_decade": slope_mat,
        "p_value": p_mat,
        "n_windows": len(cells),
        "fraction_same_sign": same_sign,
        "fraction_significant_same_sign": sig_same,
        "fraction_significant_opposite": sig_opp,
        "robustness": robust,
        "recent_windows": recent,
        "plain_language": txt,
    }
