"""Trend tests.

Methods (and where they come from):
* OLS slope + t-test + CI ............. SeaWiFS paper / Medium article (challenge resources)
  plus an AR(1) effective-sample-size correction (Santer et al. 2000) so that
  autocorrelated monthly anomalies do not produce over-confident p-values.
* Mann-Kendall (original, Hamed-Rao 1998, Yue-Wang 2004, trend-free pre-whitening Yue 2002)
* Theil-Sen slope with the Gilbert (1987) rank-based confidence interval
* Seasonal Mann-Kendall + seasonal Sen slope (Hirsch, Slack & Smith 1982)

Conventions: `t` is time in YEARS (decimal) so slopes are "units per year"; `y` may contain
NaN (missing months stay missing, they are never filled).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

from . import kernels as K


def _finite(t: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    m = np.isfinite(y) & np.isfinite(t)
    return np.asarray(t, float)[m], np.asarray(y, float)[m]


def lag1_autocorr(e: np.ndarray) -> float:
    """Lag-1 autocorrelation of a (possibly gappy) residual series; pairs with a NaN are skipped."""
    e = np.asarray(e, float)
    a, b = e[:-1], e[1:]
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 3:
        return 0.0
    ef = e[np.isfinite(e)]
    mu = ef.mean()
    den = np.sum((ef - mu) ** 2)
    if den <= 0:
        return 0.0
    num = np.sum((a[m] - mu) * (b[m] - mu))
    return float(num / den * len(ef) / max(m.sum(), 1))


def effective_n(n: int, r1: float) -> float:
    """Santer et al. (2000): n_eff = n (1 - r1) / (1 + r1), only for positive r1."""
    r = min(max(r1, 0.0), 0.99)
    return max(n * (1 - r) / (1 + r), 3.0)


# ======================================================================================
# OLS
# ======================================================================================
@dataclass
class OLSResult:
    slope: float            # units / year
    intercept: float
    se: float
    t_stat: float
    p: float                # naive (independent errors)
    ci95: tuple[float, float]
    r2: float
    n: int
    lag1_autocorr: float
    n_eff: float
    se_adj: float
    p_adj: float            # AR(1)-adjusted
    ci95_adj: tuple[float, float]
    durbin_watson: float
    residuals: np.ndarray | None = None

    def to_dict(self, per: float = 10.0) -> dict:
        d = asdict(self)
        d.pop("residuals", None)
        d["slope_per_decade"] = self.slope * per
        d["ci95_per_decade"] = [self.ci95[0] * per, self.ci95[1] * per]
        d["ci95_adj_per_decade"] = [self.ci95_adj[0] * per, self.ci95_adj[1] * per]
        return d


def ols_trend(t: np.ndarray, y: np.ndarray, alpha: float = 0.05) -> OLSResult:
    t_all = np.asarray(t, float)
    y_all = np.asarray(y, float)
    tf, yf = _finite(t_all, y_all)
    n = len(yf)
    if n < 4:
        raise ValueError("need at least 4 valid points for OLS")
    tm = tf.mean()
    ym = yf.mean()
    sxx = np.sum((tf - tm) ** 2)
    if sxx <= 0:
        raise ValueError("time values are constant")
    b = np.sum((tf - tm) * (yf - ym)) / sxx
    a = ym - b * tm
    fitted = a + b * tf
    resid = yf - fitted
    rss = float(np.sum(resid ** 2))
    tss = float(np.sum((yf - ym) ** 2))
    dof = n - 2
    se = math.sqrt(rss / dof / sxx) if dof > 0 else float("nan")
    tstat = b / se if se > 0 else (math.copysign(math.inf, b) if b else 0.0)
    p = float(2 * stats.t.sf(abs(tstat), dof)) if np.isfinite(tstat) else 0.0
    tq = stats.t.ppf(1 - alpha / 2, dof)
    # residuals on the full (gappy) grid for autocorrelation
    resid_full = y_all - (a + b * t_all)
    r1 = lag1_autocorr(resid_full)
    neff = effective_n(n, r1)
    dof_adj = max(neff - 2, 1.0)
    se_adj = se * math.sqrt(dof / dof_adj) if dof_adj > 0 else float("nan")
    t_adj = b / se_adj if se_adj > 0 else (math.copysign(math.inf, b) if b else 0.0)
    p_adj = float(2 * stats.t.sf(abs(t_adj), dof_adj)) if np.isfinite(t_adj) else 0.0
    tq_adj = stats.t.ppf(1 - alpha / 2, dof_adj)
    dw = float(np.sum(np.diff(resid) ** 2) / rss) if rss > 0 else float("nan")
    return OLSResult(
        slope=float(b), intercept=float(a), se=float(se), t_stat=float(tstat), p=p,
        ci95=(float(b - tq * se), float(b + tq * se)),
        r2=float(1 - rss / tss) if tss > 0 else 0.0, n=n,
        lag1_autocorr=float(r1), n_eff=float(neff), se_adj=float(se_adj), p_adj=p_adj,
        ci95_adj=(float(b - tq_adj * se_adj), float(b + tq_adj * se_adj)),
        durbin_watson=dw, residuals=resid_full,
    )


# ======================================================================================
# Theil-Sen
# ======================================================================================
@dataclass
class SenResult:
    slope: float             # units / year
    intercept: float
    ci95: tuple[float, float]
    n_pairs: int

    def to_dict(self, per: float = 10.0) -> dict:
        return {"slope": self.slope, "intercept": self.intercept, "ci95": list(self.ci95),
                "slope_per_decade": self.slope * per,
                "ci95_per_decade": [self.ci95[0] * per, self.ci95[1] * per], "n_pairs": self.n_pairs}


def sens_slope(t: np.ndarray, y: np.ndarray, alpha: float = 0.05) -> SenResult:
    tf, yf = _finite(t, y)
    n = len(yf)
    if n < 3:
        raise ValueError("need at least 3 valid points for Sen's slope")
    slopes = K.pairwise_slopes(tf, yf)
    slopes = np.sort(slopes[np.isfinite(slopes)])
    N = len(slopes)
    med = float(np.median(slopes))
    # Sen (1968) eq. 2.6 / Gilbert (1987) rank CI, same rounding as scipy.stats.theilslopes
    var_s = (K.mk_var_s(yf) * 18.0 - K.tie_term(tf)) / 18.0
    c = stats.norm.ppf(1 - alpha / 2) * math.sqrt(max(var_s, 0.0))
    r_lo = max(int(np.round((N - c) / 2.0)) - 1, 0)
    r_hi = min(int(np.round((N + c) / 2.0)), N - 1)
    lo = slopes[r_lo] if N else float("nan")
    hi = slopes[r_hi] if N else float("nan")
    intercept = float(np.median(yf) - med * np.median(tf))  # Conover (1980)
    return SenResult(med, intercept, (float(lo), float(hi)), N)


# ======================================================================================
# Mann-Kendall family
# ======================================================================================
@dataclass
class MKResult:
    variant: str
    s: float
    var_s: float
    z: float
    p: float
    tau: float
    trend: str               # increasing | decreasing | no trend
    n: int
    variance_correction: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


def _z_from_s(s: float, var_s: float) -> float:
    if var_s <= 0:
        return 0.0
    if s > 0:
        return (s - 1) / math.sqrt(var_s)
    if s < 0:
        return (s + 1) / math.sqrt(var_s)
    return 0.0


def _decide(z: float, alpha: float) -> tuple[float, str]:
    p = float(2 * stats.norm.sf(abs(z)))
    h = abs(z) > stats.norm.ppf(1 - alpha / 2)
    trend = "increasing" if (h and z > 0) else ("decreasing" if (h and z < 0) else "no trend")
    return p, trend


def _acf(x: np.ndarray, nlags: int) -> np.ndarray:
    """Biased ACF via FFT (O(n log n))."""
    x = np.asarray(x, float) - np.mean(x)
    n = len(x)
    nfft = 1 << (2 * n - 1).bit_length()
    f = np.fft.rfft(x, nfft)
    ac = np.fft.irfft(f * np.conj(f), nfft)[:n] / n
    if ac[0] <= 0:
        return np.zeros(nlags + 1)
    return ac[: nlags + 1] / ac[0]


def mann_kendall(t: np.ndarray, y: np.ndarray, alpha: float = 0.05, variant: str = "original",
                 lag: int | None = None) -> MKResult:
    """variant: ess_ar1 (default in the API) | original | hamed_rao | yue_wang | tfpw.

    hamed_rao / yue_wang / tfpw reproduce pymannkendall exactly (validated in the tests) but are
    liberal under strong persistence; ess_ar1 keeps the false-positive rate near alpha.

    Missing values are skipped (time order kept). Detrending for the autocorrelation
    corrections uses Sen's slope on the real time axis.
    """
    tf, yf = _finite(t, y)
    n = len(yf)
    if n < 8:
        raise ValueError("need at least 8 valid points for Mann-Kendall")

    if variant == "tfpw":
        # Yue et al. (2002) trend-free pre-whitening
        step = float(np.median(np.diff(tf)))
        pos = np.round((tf - tf[0]) / step) + 1.0
        slope_step = float(np.nanmedian(K.pairwise_slopes(pos, yf)))
        det = yf - pos * slope_step
        r1 = _acf(det, 1)[1]
        pw = det[1:] - r1 * det[:-1]
        yb = pw + pos[:-1] * slope_step
        s = float(K.mk_s(yb))
        var_s = K.mk_var_s(yb)
        z = _z_from_s(s, var_s)
        p, trend = _decide(z, alpha)
        m = len(yb)
        return MKResult("tfpw", s, var_s, z, p, s / (0.5 * m * (m - 1)), trend, m, 1.0)

    s = float(K.mk_s(yf))
    var_s = K.mk_var_s(yf)
    tau = s / (0.5 * n * (n - 1))
    corr = 1.0

    if variant == "ess_ar1":
        # Effective-sample-size correction under an AR(1) model of the Sen-detrended series:
        #   n/n* = 1 + 2 * sum_{k=1}^{n-1} (1 - k/n) * r1^k     (Lettenmaier 1976; Yue & Wang 2004 eq. for AR(1))
        # r1 is bias-corrected for small samples (Marriott & Pope 1954: E[r1] ~ rho - (1 + 3 rho) / n).
        # Simulations in tests/test_statistics.py show this keeps the false-positive rate near alpha
        # for 0 <= phi <= 0.85, unlike the all-lag Hamed-Rao / Yue-Wang defaults.
        step = float(np.median(np.diff(tf))) if n > 1 else 1.0
        pos = np.round((tf - tf[0]) / step) + 1.0
        slope_step = float(np.nanmedian(K.pairwise_slopes(pos, yf)))
        det = yf - pos * slope_step
        r1 = float(_acf(det, 1)[1])
        r1 = min(max((r1 * n + 1.0) / (n - 3.0), 0.0), 0.95)   # inverse of the Marriott-Pope bias
        k = np.arange(1, n, dtype=float)
        corr = float(1 + 2 * np.sum((1 - k / n) * r1 ** k))
        var_s = var_s * corr
        z = _z_from_s(s, var_s)
        p, trend = _decide(z, alpha)
        return MKResult("ess_ar1", s, var_s, z, p, tau, trend, n, corr)

    if variant in ("hamed_rao", "yue_wang"):
        # Detrend with Sen's slope on integer step positions (real positions, so gaps are
        # respected). For gap-free data this is exactly pymannkendall's x - (1..n) * slope.
        step = float(np.median(np.diff(tf))) if n > 1 else 1.0
        pos = np.round((tf - tf[0]) / step) + 1.0
        slope_step = float(np.nanmedian(K.pairwise_slopes(pos, yf)))
        det = yf - pos * slope_step
        maxlag = n - 1 if lag is None else min(lag, n - 1)
        if variant == "hamed_rao":
            ranks = stats.rankdata(det)
            acf = _acf(ranks, maxlag)
            bound = stats.norm.ppf(1 - alpha / 2) / math.sqrt(n)
            i = np.arange(1, maxlag + 1, dtype=float)
            rho = acf[1:maxlag + 1]
            sig = (rho > bound) | (rho < -bound)
            sni = np.sum(((n - i) * (n - i - 1) * (n - i - 2) * rho)[sig])
            corr = 1 + (2.0 / (n * (n - 1) * (n - 2))) * sni
        else:
            acf = _acf(det, maxlag)
            i = np.arange(1, maxlag + 1, dtype=float)
            corr = 1 + 2 * np.sum((1 - i / n) * acf[1:maxlag + 1])
        corr = float(max(corr, 1e-6))
        var_s = var_s * corr
    elif variant != "original":
        raise ValueError(f"unknown MK variant {variant}")

    z = _z_from_s(s, var_s)
    p, trend = _decide(z, alpha)
    return MKResult(variant, s, var_s, z, p, tau, trend, n, corr)


# ======================================================================================
# Seasonal Mann-Kendall (Hirsch et al. 1982)
# ======================================================================================
@dataclass
class SeasonalMKResult:
    s: float
    var_s: float
    z: float
    p: float
    trend: str
    sen_slope: float         # units / year (median of within-season pairwise slopes)
    n_seasons_used: int
    per_season: list[dict]

    def to_dict(self, per: float = 10.0) -> dict:
        d = asdict(self)
        d["sen_slope_per_decade"] = self.sen_slope * per
        return d


def seasonal_mann_kendall(years: np.ndarray, season: np.ndarray, y: np.ndarray, period: int = 12,
                          alpha: float = 0.05) -> SeasonalMKResult:
    """years: decimal or integer year of each sample; season: 0..period-1."""
    years = np.asarray(years, float)
    season = np.asarray(season, np.int64)
    y = np.asarray(y, float)
    m = np.isfinite(y)
    years, season, y = years[m], season[m], y[m]
    S = 0.0
    V = 0.0
    used = 0
    per_season = []
    for p in range(period):
        sel = season == p
        ys = y[sel]
        if len(ys) < 3:
            per_season.append({"season": p, "n": int(len(ys)), "s": None})
            continue
        s = float(K.mk_s(ys))
        v = K.mk_var_s(ys)
        S += s
        V += v
        used += 1
        per_season.append({"season": p, "n": int(len(ys)), "s": s, "var_s": v,
                           "z": _z_from_s(s, v), "p": _decide(_z_from_s(s, v), alpha)[0]})
    z = _z_from_s(S, V)
    p, trend = _decide(z, alpha)
    slopes = K.seasonal_pairwise_slopes(np.floor(years + 1e-9), season, y, period)
    slopes = slopes[np.isfinite(slopes)]
    sen = float(np.median(slopes)) if len(slopes) else float("nan")
    return SeasonalMKResult(S, V, z, p, trend, sen, used, per_season)
