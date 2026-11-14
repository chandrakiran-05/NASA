"""Compiled numerical kernels (numba, cached to disk).

* `mk_s`            Mann-Kendall S in O(n log n) with a Fenwick tree over dense ranks
                    (Knight 1966 idea), instead of the textbook O(n^2) double loop.
* `pairwise_slopes` all (y_j - y_i) / (t_j - t_i) for Theil-Sen, O(n^2) but compiled.
* `seasonal_pairwise_slopes` within-season pairwise slopes (Hirsch 1982 seasonal Sen).
* `pelt_linear`     PELT change-point search (Killick et al. 2012) with a piecewise-LINEAR
                    segment cost evaluated in O(1) from prefix sums.
* `cube_*`          per-pixel trend kernels for gridded trend maps (parallel over pixels).

Every kernel has a pure-NumPy fallback so the service still runs if numba is missing.
"""
from __future__ import annotations

import numpy as np

try:  # pragma: no cover - import guard
    from numba import njit, prange

    HAVE_NUMBA = True
except Exception:  # noqa: BLE001
    HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        def deco(f):
            return f
        if args and callable(args[0]):
            return args[0]
        return deco

    prange = range  # type: ignore


# --------------------------------------------------------------------------------------
# Mann-Kendall S
# --------------------------------------------------------------------------------------
@njit(cache=True)
def _mk_s_fenwick(ranks: np.ndarray, n_unique: int) -> np.int64:
    tree = np.zeros(n_unique + 1, dtype=np.int64)
    s = np.int64(0)
    for j in range(ranks.shape[0]):
        r = ranks[j] + 1  # 1-based
        # count of previous values with rank < r  (strictly smaller)
        less = np.int64(0)
        i = r - 1
        while i > 0:
            less += tree[i]
            i -= i & (-i)
        # count of previous values with rank <= r
        leq = np.int64(0)
        i = r
        while i > 0:
            leq += tree[i]
            i -= i & (-i)
        greater = j - leq
        s += less - greater  # x_j > x_i counts +1, x_j < x_i counts -1
        i = r
        while i <= n_unique:
            tree[i] += 1
            i += i & (-i)
    return s


def mk_s(x: np.ndarray) -> int:
    """Mann-Kendall S for a NaN-free 1-D array (time order = array order)."""
    x = np.asarray(x, dtype=np.float64)
    uniq, ranks = np.unique(x, return_inverse=True)
    return int(_mk_s_fenwick(ranks.astype(np.int64), uniq.shape[0]))


def mk_s_bruteforce(x: np.ndarray) -> int:
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    s = 0
    for k in range(n - 1):
        s += int(np.sign(x[k + 1:] - x[k]).sum())
    return s


def tie_term(x: np.ndarray) -> float:
    """sum t(t-1)(2t+5) over tie groups."""
    _, counts = np.unique(np.asarray(x, dtype=np.float64), return_counts=True)
    c = counts[counts > 1].astype(np.float64)
    return float(np.sum(c * (c - 1) * (2 * c + 5)))


def mk_var_s(x: np.ndarray) -> float:
    n = float(len(x))
    return (n * (n - 1) * (2 * n + 5) - tie_term(x)) / 18.0


# --------------------------------------------------------------------------------------
# Theil-Sen pairwise slopes
# --------------------------------------------------------------------------------------
@njit(cache=True)
def pairwise_slopes(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    n = y.shape[0]
    out = np.empty(n * (n - 1) // 2, dtype=np.float64)
    k = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            dt = t[j] - t[i]
            out[k] = (y[j] - y[i]) / dt if dt != 0 else np.nan
            k += 1
    return out


@njit(cache=True)
def seasonal_pairwise_slopes(years: np.ndarray, season: np.ndarray, y: np.ndarray, period: int) -> np.ndarray:
    """Pairwise slopes per year computed only between observations of the same season."""
    n = y.shape[0]
    # upper bound on pair count
    counts = np.zeros(period, dtype=np.int64)
    for i in range(n):
        counts[season[i]] += 1
    total = 0
    for p in range(period):
        total += counts[p] * (counts[p] - 1) // 2
    out = np.empty(total, dtype=np.float64)
    k = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            if season[i] == season[j]:
                dt = years[j] - years[i]
                out[k] = (y[j] - y[i]) / dt if dt != 0 else np.nan
                k += 1
    return out[:k]


# --------------------------------------------------------------------------------------
# PELT with piecewise-linear cost (prefix sums -> O(1) segment cost)
# --------------------------------------------------------------------------------------
@njit(cache=True)
def _seg_cost(cs: np.ndarray, a: int, b: int) -> float:
    """RSS of OLS line fitted to points a..b-1 (half-open) using prefix sums.

    cs rows: 0:count 1:sum t 2:sum t^2 3:sum y 4:sum y^2 5:sum t*y
    """
    n = cs[0, b] - cs[0, a]
    st = cs[1, b] - cs[1, a]
    stt = cs[2, b] - cs[2, a]
    sy = cs[3, b] - cs[3, a]
    syy = cs[4, b] - cs[4, a]
    sty = cs[5, b] - cs[5, a]
    if n < 2:
        return 0.0
    sxx = stt - st * st / n
    syy_c = syy - sy * sy / n
    sxy = sty - st * sy / n
    if sxx <= 1e-12:
        return max(syy_c, 0.0)
    rss = syy_c - sxy * sxy / sxx
    return max(rss, 0.0)


def prefix_sums(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    cs = np.zeros((6, len(y) + 1), dtype=np.float64)
    cs[0, 1:] = np.cumsum(np.ones_like(y))
    cs[1, 1:] = np.cumsum(t)
    cs[2, 1:] = np.cumsum(t * t)
    cs[3, 1:] = np.cumsum(y)
    cs[4, 1:] = np.cumsum(y * y)
    cs[5, 1:] = np.cumsum(t * y)
    return cs


@njit(cache=True)
def pelt_linear(cs: np.ndarray, penalty: float, min_size: int) -> np.ndarray:
    """Exact optimal partition minimising  sum_seg RSS_linear(seg) + penalty * (#segments).

    Pruning rule (Killick 2012, K = 0 for RSS costs): candidate s is dropped once
    F[s] + C(s, t) > F[t]. Returns change-point indices (segment starts), excluding 0.
    """
    n = int(cs[0, cs.shape[1] - 1])
    F = np.full(n + 1, np.inf)
    F[0] = -penalty
    last = np.zeros(n + 1, dtype=np.int64)
    cand = np.empty(n + 2, dtype=np.int64)
    vals = np.empty(n + 2, dtype=np.float64)
    n_cand = 1
    cand[0] = 0
    for ts in range(min_size, n + 1):
        best = np.inf
        best_s = 0
        for k in range(n_cand):
            s = cand[k]
            if ts - s < min_size:
                vals[k] = np.inf
                continue
            v = F[s] + _seg_cost(cs, s, ts) + penalty
            vals[k] = v
            if v < best:
                best = v
                best_s = s
        F[ts] = best
        last[ts] = best_s
        m = 0
        for k in range(n_cand):
            s = cand[k]
            if ts - s < min_size or vals[k] - penalty <= best:
                cand[m] = s
                m += 1
        cand[m] = ts
        m += 1
        n_cand = m
    # backtrack
    cps = []
    t = n
    while t > 0:
        s = last[t]
        if s > 0:
            cps.append(s)
        t = s
    out = np.empty(len(cps), dtype=np.int64)
    for i in range(len(cps)):
        out[i] = cps[len(cps) - 1 - i]
    return out


# --------------------------------------------------------------------------------------
# Gridded (cube) kernels: data shape (time, npix)
# --------------------------------------------------------------------------------------
@njit(cache=True, parallel=True)
def cube_ols(t: np.ndarray, Y: np.ndarray, min_valid: int):
    nt, npix = Y.shape
    slope = np.full(npix, np.nan)
    se = np.full(npix, np.nan)
    r1 = np.full(npix, np.nan)
    nvalid = np.zeros(npix, dtype=np.int64)
    for p in prange(npix):
        n = 0
        st = 0.0
        sy = 0.0
        for i in range(nt):
            v = Y[i, p]
            if v == v:
                n += 1
                st += t[i]
                sy += v
        nvalid[p] = n
        if n < min_valid:
            continue
        mt = st / n
        my = sy / n
        sxx = 0.0
        sxy = 0.0
        for i in range(nt):
            v = Y[i, p]
            if v == v:
                sxx += (t[i] - mt) ** 2
                sxy += (t[i] - mt) * (v - my)
        if sxx <= 0:
            continue
        b = sxy / sxx
        a = my - b * mt
        rss = 0.0
        num = 0.0
        den = 0.0
        prev = np.nan
        for i in range(nt):
            v = Y[i, p]
            if v == v:
                e = v - a - b * t[i]
                rss += e * e
                den += e * e
                if prev == prev:
                    num += e * prev
                prev = e
            else:
                prev = np.nan
        slope[p] = b
        se[p] = np.sqrt(rss / (n - 2) / sxx) if n > 2 else np.nan
        r1[p] = num / den if den > 0 else 0.0
    return slope, se, r1, nvalid


@njit(cache=True, parallel=True)
def cube_mk_s(Y: np.ndarray, min_valid: int):
    nt, npix = Y.shape
    S = np.zeros(npix, dtype=np.float64)
    V = np.full(npix, np.nan)
    for p in prange(npix):
        n = 0
        for i in range(nt):
            if Y[i, p] == Y[i, p]:
                n += 1
        if n < min_valid:
            S[p] = np.nan
            continue
        x = np.empty(n)
        k = 0
        for i in range(nt):
            v = Y[i, p]
            if v == v:
                x[k] = v
                k += 1
        s = 0.0
        for a in range(n - 1):
            for b in range(a + 1, n):
                d = x[b] - x[a]
                if d > 0:
                    s += 1.0
                elif d < 0:
                    s -= 1.0
        # tie correction
        xs = np.sort(x)
        tie = 0.0
        run = 1
        for i in range(1, n + 1):
            if i < n and xs[i] == xs[i - 1]:
                run += 1
            else:
                if run > 1:
                    tie += run * (run - 1) * (2 * run + 5)
                run = 1
        S[p] = s
        V[p] = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    return S, V


def warmup() -> None:
    """Trigger JIT compilation once at startup so the first user request is fast."""
    t = np.arange(40, dtype=np.float64)
    y = np.sin(t) + 0.01 * t
    mk_s(y)
    pairwise_slopes(t, y)
    seasonal_pairwise_slopes(t / 12.0, (np.arange(40) % 12).astype(np.int64), y, 12)
    pelt_linear(prefix_sums(t, y), 10.0, 5)
    Y = np.vstack([y, y]).T.copy()
    cube_ols(t, Y, 10)
    cube_mk_s(Y, 10)
