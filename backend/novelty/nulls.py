"""F5 — Could It Be Chance? Block-bootstrap null distribution + visual lineup.

The trend is removed from the deseasonalized series, then the residuals are resampled in
12-month blocks (moving-block bootstrap, circular), which keeps the month-to-month persistence.
Every shuffled series is a world with the same noise but NO trend. The real slope is compared
with 1,000 such slopes ("permutation p"), and the real series is hidden among 19 shuffles.
All shuffles are labelled "simulated from your data, not observations".
"""
from __future__ import annotations

import numpy as np

from ..analysis.deseason import deseasonalize
from ..analysis.trend import ols_trend
from ..timeseries.model import MonthlySeries


def _block_indices(n: int, block: int, n_samples: int, rng: np.random.Generator) -> np.ndarray:
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_samples, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(n_samples, -1)[:, :n]


def _slopes(t: np.ndarray, Y: np.ndarray) -> np.ndarray:
    m = np.isfinite(Y)
    n = m.sum(1)
    tt = np.where(m, t[None, :], 0.0)
    yy = np.where(m, Y, 0.0)
    tm = tt.sum(1) / n
    ym = yy.sum(1) / n
    sxx = (np.where(m, (t[None, :] - tm[:, None]) ** 2, 0)).sum(1)
    sxy = (np.where(m, (t[None, :] - tm[:, None]) * (Y - ym[:, None]), 0)).sum(1)
    return sxy / sxx


def null_lineup(ms: MonthlySeries, *, n_null: int = 1000, n_panels: int = 19, block: int = 12, seed: int = 2026) -> dict:
    t = ms.t_years()
    des = deseasonalize(ms, "stl").deseasonalized
    o = ols_trend(t, des)
    resid = des - (o.intercept + o.slope * t)
    valid = np.isfinite(resid)
    pool = resid[valid]
    n = len(des)
    rng = np.random.default_rng(seed)
    idx = _block_indices(len(pool), block, n_null + n_panels, rng)
    sim = np.full((n_null + n_panels, n), np.nan)
    sim[:, valid] = pool[idx] + o.intercept + o.slope * t[valid].mean()   # same level, zero trend
    null_slopes = _slopes(t, sim[:n_null]) * 10
    real = o.slope * 10
    perm_p = float((1 + np.sum(np.abs(null_slopes) >= abs(real))) / (1 + n_null))
    panels = sim[n_null:]
    real_index = int(rng.integers(0, n_panels + 1))
    lineup = [p for p in panels]
    lineup.insert(real_index, des)
    pct = float(np.mean(np.abs(null_slopes) < abs(real)) * 100)
    return {
        "method": f"moving-block bootstrap of detrended residuals ({block}-month blocks, seed {seed})",
        "label": "Simulated from your data, not observations.",
        "real_slope_per_decade": real,
        "null_slopes_per_decade": [round(float(x), 6) for x in null_slopes],
        "perm_p": perm_p,
        "real_percentile": pct,
        "lineup": {"time": [d.strftime("%Y-%m-%d") for d in ms.time],
                   "panels": [[None if not np.isfinite(v) else round(float(v), 5) for v in p] for p in lineup],
                   "real_index": real_index},
        "plain_language": (f"Out of {n_null} trend-free worlds with the same noise, {100 - pct:.1f}% produced a slope at "
                           f"least as steep as the real one (permutation p = {perm_p:.3f})."),
        "limit": "Failing to spot the real series in the lineup does not mean there is no trend.",
    }
