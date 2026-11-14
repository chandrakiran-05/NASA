"""Per-pixel trend maps — "WHERE inside my region is it changing?"

Input: a monthly cube (time, lat, lon). Each pixel is deseasonalized (monthly climatology),
then OLS (AR(1)-adjusted) and Mann-Kendall run in compiled parallel kernels. Field
significance uses Benjamini-Hochberg with alpha_FDR = 2*alpha, as recommended by Wilks (2016,
BAMS, "The stippling shows statistically significant grid points").

Outputs slope / p-value grids, a significance mask, and area-weighted (cos latitude) fractions
of the region that are significantly rising or falling — including whether BOTH happen inside
the same region (the challenge's "opposite trends" case).
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats
from statsmodels.stats.multitest import multipletests

from ..analysis import kernels as K


def _bh_mask(p: np.ndarray, q: float) -> np.ndarray:
    out = np.zeros(p.shape, bool)
    ok = np.isfinite(p)
    if ok.sum():
        rej, *_ = multipletests(p[ok], alpha=q, method="fdr_bh")
        out[ok] = rej
    return out


def cube_trends(values: np.ndarray, months: np.ndarray, lat: np.ndarray, lon: np.ndarray, *,
                alpha: float = 0.05, min_valid_fraction: float = 0.7) -> dict:
    """values: (nt, ny, nx) float with NaN; months: (nt,) 1..12; lat (ny,), lon (nx,)."""
    nt, ny, nx = values.shape
    Y = values.reshape(nt, ny * nx).astype(np.float64)
    # climatology anomalies per pixel (vectorised)
    m0 = np.asarray(months) - 1
    for m in range(12):
        sel = m0 == m
        if sel.any():
            with np.errstate(invalid="ignore"):
                Y[sel] -= np.nanmean(Y[sel], axis=0, keepdims=True)
    t = np.arange(nt, dtype=np.float64) / 12.0
    min_valid = max(int(min_valid_fraction * nt), 24)
    slope, se, r1, nvalid = K.cube_ols(t, np.ascontiguousarray(Y), min_valid)
    S, V = K.cube_mk_s(np.ascontiguousarray(Y), min_valid)

    r = np.clip(np.nan_to_num(r1, nan=0.0), 0.0, 0.95)
    neff = np.maximum(nvalid * (1 - r) / (1 + r), 3.0)
    se_adj = se * np.sqrt((nvalid - 2) / np.maximum(neff - 2, 1.0))
    with np.errstate(invalid="ignore", divide="ignore"):
        t_adj = slope / se_adj
        p_ols = 2 * stats.t.sf(np.abs(t_adj), np.maximum(neff - 2, 1.0))
        z = np.where(S > 0, (S - 1) / np.sqrt(V), np.where(S < 0, (S + 1) / np.sqrt(V), 0.0))
        p_mk = 2 * stats.norm.sf(np.abs(z))
    p_ols[~np.isfinite(slope)] = np.nan
    p_mk[~np.isfinite(S)] = np.nan
    p_comb = np.fmax(p_ols, p_mk)
    sig = _bh_mask(p_comb, 2 * alpha)

    w = np.repeat(np.cos(np.deg2rad(lat))[:, None], nx, axis=1).ravel()
    valid = np.isfinite(slope)
    wv = w[valid].sum() if valid.any() else 1.0
    frac_up = float(w[sig & (slope > 0)].sum() / wv) if valid.any() else 0.0
    frac_down = float(w[sig & (slope < 0)].sum() / wv) if valid.any() else 0.0
    mean_slope = float(np.nansum(slope * w) / np.nansum(np.where(valid, w, 0))) if valid.any() else None

    def grid(a):
        g = a.reshape(ny, nx).astype(float)
        return [[None if not math.isfinite(v) else float(v) for v in row] for row in g]

    if frac_up > 0.05 and frac_down > 0.05:
        txt = (f"Mixed picture inside the region: {frac_up * 100:.0f}% of the area is significantly rising and "
               f"{frac_down * 100:.0f}% significantly falling.")
    elif frac_up > 0 or frac_down > 0:
        d, f = ("rising", frac_up) if frac_up >= frac_down else ("falling", frac_down)
        txt = f"{f * 100:.0f}% of the area shows a significant {d} trend (field-significance corrected)."
    else:
        txt = "No grid cell has a significant trend after the field-significance correction."
    return {
        "method": "per-pixel climatology anomalies, OLS (AR(1)-adjusted) + Mann-Kendall, BH-FDR at 2*alpha (Wilks 2016)",
        "lat": [float(v) for v in lat], "lon": [float(v) for v in lon],
        "slope_per_decade": grid(slope * 10), "p_ols_adj": grid(p_ols), "p_mk": grid(p_mk),
        "significant": [[bool(v) for v in row] for row in sig.reshape(ny, nx)],
        "n_valid": grid(nvalid.astype(float)),
        "area_fraction_rising": frac_up, "area_fraction_falling": frac_down,
        "area_mean_slope_per_decade": None if mean_slope is None else mean_slope * 10,
        "plain_language": txt,
    }
