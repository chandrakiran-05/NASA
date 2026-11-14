"""WHEN did it change? Calibrated BEAST change-onset detection (Trend Forensics, docs/07).

BEAST (Zhao et al. 2019, Remote Sens. Environ. 232:111181) is a Bayesian ensemble of
piecewise-linear trend models. It returns, for every month, the posterior probability that the
trend changed there, plus the posterior for the number of changes.

Why it is NOT run raw on monthly data
-------------------------------------
BEAST's likelihood assumes independent noise. Monthly climate anomalies are persistent (lag-1
autocorrelation phi ~ 0.3-0.8). In our calibration study (scripts/onset_calibration.py), raw
BEAST on a steady trend with phi = 0.5 reported a "confident" change point (>= 80% probability
within a 2-year window) in 28 of 30 series that had no change at all. Three safeguards fix that:

1. Memory-matched blocks. Seasonal anomalies are averaged into blocks of
   L = ceil((1+phi)/(1-phi)) months (the AR(1) decorrelation time; 1..12). Block means are close
   to independent, which is what BEAST assumes. A block counts only if half its months are valid;
   nothing is interpolated.
2. Window probability. A single change spreads its posterior over neighbouring dates, so we
   report the probability of a change inside a +/- 1-year window, not at one month.
3. Surrogate calibration ("could this change be chance?"). We simulate K series that have the
   same seasonal-anomaly trend, AR(1) memory and noise and the same missing months, but NO
   change, and run the identical BEAST procedure on each. The change statistic (F-test of a
   broken-trend vs single-trend model at BEAST's date) is compared with that null distribution:
   p_calibrated = (1 + #null >= observed) / (K + 1). The search over dates is inside the null,
   so p_calibrated is honest about having looked everywhere.

Measured on synthetic AR(1) series (288 months, K = 49, 25 trials each):
    phi    false "confirmed" changes   true break (jump + slope change) confirmed
    0.0          0 / 25                      25 / 25
    0.5          1 / 25                      20 / 25
    0.7          2 / 25                      10 / 25
    0.8          1 / 25                       4 / 25
False alarms stay near the 5% target; power falls with persistence, which is the honest answer
(very persistent data simply cannot date a change precisely).

Output wording rules: a change point is a date when the trend's behaviour changed; it is not a
cause. A change near a cited instrument/observing-system seam is labelled "possible instrument
effect".
"""
from __future__ import annotations

import contextlib
import threading
import math
import sys

import numpy as np
import pandas as pd

from ..analysis.deseason import deseasonalize
from ..analysis.trend import ols_trend
from ..timeseries.model import MonthlySeries

try:  # optional dependency: pip install rbeast (MIT)
    import Rbeast as _rb
except ImportError:  # pragma: no cover - exercised only when the package is missing
    _rb = None

CITATION = {"text": "Zhao K. et al. 2019, Detecting change-point, trend, and seasonality in satellite time series "
                    "data ... : A Bayesian ensemble algorithm. Remote Sens. Environ. 232:111181",
            "doi": "10.1016/j.rse.2019.04.034"}
MIN_VALID_MONTHS = 72
SEAM_WINDOW_MONTHS = 18


def available() -> bool:
    return _rb is not None


_HOOK_LOCK = threading.Lock()   # sys.unraisablehook is process-global; parallel swaps left it replaced


@contextlib.contextmanager
def _quiet_unraisable():
    """Rbeast's C extension emits a harmless 'Exception ignored' message on Python >= 3.12."""
    with _HOOK_LOCK:                # Rbeast holds the GIL anyway, so this costs no parallelism
        old = sys.unraisablehook
        sys.unraisablehook = lambda *_: None
        try:
            yield
        finally:
            sys.unraisablehook = old


# ------------------------------------------------------------------ helpers
def _line_and_memory(t: np.ndarray, a: np.ndarray) -> tuple[float, float, float, float]:
    ok = np.isfinite(a)
    b, c = np.polyfit(t[ok], a[ok], 1)
    r = a - (b * t + c)
    rr = r[ok] - r[ok].mean()
    phi = float(np.clip(np.sum(rr[1:] * rr[:-1]) / np.sum(rr * rr), 0.0, 0.95)) if len(rr) > 2 else 0.0
    sd = float(np.nanstd(r))
    return float(b), float(c), phi, sd


def block_length(phi: float) -> int:
    return int(np.clip(math.ceil((1 + phi) / (1 - phi)), 1, 12))


def _blocks(a: np.ndarray, L: int) -> np.ndarray:
    m = len(a) // L
    B = a[: m * L].reshape(m, L)
    cnt = np.isfinite(B).sum(1)
    with np.errstate(all="ignore"), _warnings_off():
        v = np.nanmean(B, axis=1)
    return np.where(cnt >= max(1, L // 2), v, np.nan)


@contextlib.contextmanager
def _warnings_off():
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _beast_blocks(b: np.ndarray, L: int, start_year: float, seed: int):
    with _quiet_unraisable():
        return _rb.beast(b, start=start_year, deltat=L / 12.0, season="none", quiet=1, print_progress=0,
                         print_options=0, mcmc_seed=seed, tseg_minlen=max(2, 24 // L), tcp_minmax=[0, 5])


def _window(L: int) -> int:
    return max(1, 12 // L)


def _window_prob(cp_occ: np.ndarray, L: int) -> np.ndarray:
    h = _window(L)
    return np.convolve(np.nan_to_num(cp_occ), np.ones(2 * h + 1), "same")


def _f_stat(t: np.ndarray, a: np.ndarray, k: int) -> float:
    """F statistic of 'trend + level shift + slope change at k' vs 'single trend' (2 extra params)."""
    ok = np.isfinite(a)
    d = (np.arange(len(a)) >= k).astype(float)
    X1 = np.c_[np.ones(len(a)), t]
    X2 = np.c_[X1, d, d * (t - t[k])]
    y = a[ok]
    r1 = float(np.sum((y - X1[ok] @ np.linalg.lstsq(X1[ok], y, rcond=None)[0]) ** 2))
    r2 = float(np.sum((y - X2[ok] @ np.linalg.lstsq(X2[ok], y, rcond=None)[0]) ** 2))
    dof = int(ok.sum()) - 4
    if r2 <= 0 or dof <= 0:
        return float("inf")
    return (r1 - r2) / 2.0 / (r2 / dof)


def _month_index(block_idx: int, L: int, n: int, edge: int) -> int:
    return int(np.clip(block_idx * L + L // 2, edge, n - edge))


def _top_change_stat(t: np.ndarray, a: np.ndarray, L: int, start_year: float, seed: int, edge: int) -> float:
    """Identical procedure to the observed series: BEAST window peak, then month refinement."""
    o = _beast_blocks(_blocks(a, L), L, start_year, seed)
    w = _window_prob(o.trend.cpOccPr, L)
    j, h, n = int(np.argmax(w)), _window(L), len(a)
    m_lo = int(np.clip(max(0, j - h) * L, edge, n - edge))
    m_hi = int(np.clip(min(len(w), j + h + 1) * L, edge, n - edge))
    return max(_f_stat(t, a, kk) for kk in range(m_lo, max(m_lo + 1, m_hi + 1)))


def _ar1(phi: float, n: int, rng: np.random.Generator) -> np.ndarray:
    z = rng.normal(0.0, 1.0, n)
    e = np.empty(n)
    e[0] = z[0] / math.sqrt(max(1 - phi * phi, 1e-6))
    for i in range(1, n):
        e[i] = phi * e[i - 1] + z[i]
    return e


# ------------------------------------------------------------------ main
def change_onset(ms: MonthlySeries, *, seams: list[dict] | None = None, pelt_breaks: list[dict] | None = None,
                 n_surrogates: int = 49, seed: int = 2026, alpha: float = 0.05, max_events: int = 3,
                 min_event_prob: float = 0.5) -> dict:
    if not available():
        return {"status": "unavailable", "plain_language": "Change dating needs the 'rbeast' package (pip install rbeast).",
                "events": []}
    n_valid = ms.n_valid
    if n_valid < MIN_VALID_MONTHS:
        return {"status": "too_short", "events": [],
                "plain_language": f"Need at least {MIN_VALID_MONTHS} valid months to date a change; this record has {n_valid}."}

    a = deseasonalize(ms, "climatology").deseasonalized       # seasonal anomalies, NaN where missing
    t = ms.t_years()
    n = len(a)
    start_year = ms.time[0].year + (ms.time[0].month - 1) / 12.0
    slope, icpt, phi, sd = _line_and_memory(t, a)
    L = block_length(phi)
    edge = 24 if n >= 96 else max(12, n // 4)

    # ---- BEAST on memory-matched blocks
    b = _blocks(a, L)
    if np.isfinite(b).sum() < 12:
        return {"status": "too_short", "events": [],
                "plain_language": "Too few valid blocks after matching the data's memory; cannot date a change."}
    o = _beast_blocks(b, L, start_year, seed)
    tr = o.trend
    occ = np.nan_to_num(np.asarray(tr.cpOccPr, float))
    w = _window_prob(occ, L)
    ncp_pr = [float(x) for x in np.nan_to_num(np.asarray(tr.ncpPr, float))]
    p_no_change = ncp_pr[0] if ncp_pr else None

    # ---- surrogate null for the change statistic
    rng = np.random.default_rng(seed)
    sig = sd * math.sqrt(max(1 - phi * phi, 1e-6))
    miss = ~np.isfinite(a)
    null = []
    for i in range(int(n_surrogates)):
        s = slope * t + icpt + _ar1(phi, n, rng) * sig
        s[miss] = np.nan
        null.append(_top_change_stat(t, s, L, start_year, seed + 1 + i, edge))
    null_arr = np.asarray(null)

    # ---- pick events (greedy peaks of the window probability)
    h = _window(L)
    work = w.copy()
    block_t = start_year + (np.arange(len(b)) * L + (L - 1) / 2.0) / 12.0
    events = []
    for _ in range(max_events):
        j = int(np.argmax(work))
        if work[j] < 0.2:
            break
        lo, hi = max(0, j - h), min(len(work), j + h + 1)
        mass = occ[lo:hi]
        prob = float(min(1.0, mass.sum()))
        if mass.sum() > 0:
            wts = mass / mass.sum()
            dec = float(np.sum(block_t[lo:hi] * wts))
            cdf = np.cumsum(wts)
            q05 = float(block_t[lo:hi][np.searchsorted(cdf, 0.05)])
            q95 = float(block_t[lo:hi][min(np.searchsorted(cdf, 0.95), hi - lo - 1)])
        else:
            dec = q05 = q95 = float(block_t[j])
        # refine to month resolution: best broken-trend fit inside BEAST's window
        m_lo = int(np.clip(lo * L, edge, n - edge))
        m_hi = int(np.clip(hi * L, edge, n - edge))
        cand = range(m_lo, max(m_lo + 1, m_hi + 1))
        fs = [(_f_stat(t, a, kk), kk) for kk in cand]
        F, k = max(fs) if fs else (_f_stat(t, a, edge), edge)
        p_cal = float((1 + np.sum(null_arr >= F)) / (len(null_arr) + 1))
        half = (L / 2.0 + 0.5) / 12.0
        refined = start_year + k / 12.0
        events.append({"k": k, "decimal_year": dec, "probability": prob,
                       "interval90": [min(q05 - half, refined), max(q95 + half, refined)],
                       "f_stat": float(F), "p_calibrated": p_cal})
        # one change spreads over neighbouring windows: suppress anything within 2 windows of it
        work[max(0, j - 2 * h): min(len(work), j + 2 * h + 1)] = 0.0
    events = [e for e in events if e["probability"] >= min_event_prob or e is events[0]] if events else []

    def ym(dec: float) -> str:
        y = int(math.floor(dec + 1e-9))
        m = int(np.clip(round((dec - y) * 12) + 1, 1, 12))
        return f"{y:04d}-{m:02d}"

    for e in events:
        e["date"] = ms.time[e["k"]].strftime("%Y-%m")
        e["interval90"] = [ym(e["interval90"][0]), ym(e["interval90"][1])]
        e["status"] = ("confirmed" if e["p_calibrated"] < alpha and e["probability"] >= min_event_prob else
                       "possible" if e["probability"] >= min_event_prob else "weak")
        e["near_seam"] = None
        for s in seams or []:
            try:
                sd_ = pd.Timestamp(s["date"] + "-01")
            except (KeyError, ValueError, TypeError):
                continue
            if abs((ms.time[e["k"]] - sd_).days) <= SEAM_WINDOW_MONTHS * 30.5:
                e["near_seam"] = {"id": s.get("id"), "date": s["date"], "description": s.get("description"),
                                  "citation": s.get("citation"), "url": s.get("url"),
                                  "label": "possible instrument effect"}
                break
        e["agrees_with_pelt"] = bool(pelt_breaks) and any(
            abs((ms.time[e["k"]] - pd.Timestamp(pb["date"] + "-01")).days) <= 24 * 30.5 for pb in pelt_breaks)

    for e in events[1:]:          # surrogates calibrate only the strongest change; later ones stay 'possible'
        if e["status"] == "confirmed":
            e["status"] = "possible"

    # ---- segment trends (on the original seasonal anomalies, AR(1)-adjusted) for confirmed events
    confirmed = sorted([e for e in events if e["status"] == "confirmed"], key=lambda e: e["k"])
    segments = []
    bounds = [0, *[e["k"] for e in confirmed], n]
    for s0, s1 in zip(bounds[:-1], bounds[1:]):
        seg = a[s0:s1]
        if np.isfinite(seg).sum() < 24:
            continue
        o_ = ols_trend(t[s0:s1], seg, alpha)
        segments.append({"start": ms.time[s0].strftime("%Y-%m"), "end": ms.time[s1 - 1].strftime("%Y-%m"),
                         "slope_per_decade": o_.slope * 10,
                         "ci95_adj_per_decade": [o_.ci95_adj[0] * 10, o_.ci95_adj[1] * 10],
                         "p_adj": o_.p_adj, "significant": bool(o_.p_adj < alpha)})
    pairs = zip(confirmed, segments[:-1], segments[1:]) if len(segments) == len(confirmed) + 1 else []
    for e, s_before, s_after in pairs:
        sb, sa = s_before["slope_per_decade"], s_after["slope_per_decade"]
        if np.sign(sb) != np.sign(sa) and (s_before["significant"] or s_after["significant"]):
            e["kind"] = "reversal"
        elif abs(sa) > abs(sb):
            e["kind"] = "acceleration"
        else:
            e["kind"] = "slowdown"
        e["slope_before_per_decade"], e["slope_after_per_decade"] = sb, sa

    # ---- current direction probability from the posterior slope (block model)
    slp_pos = np.asarray(tr.slpSgnPosPr, float)
    slp_zero = np.asarray(tr.slpSgnZeroPr, float)
    tail = max(1, 12 // L)
    p_up = float(np.nanmean(slp_pos[-tail:]))
    p_flat = float(np.nanmean(slp_zero[-tail:]))
    p_down = float(max(0.0, 1.0 - p_up - p_flat))

    # ---- month-level ribbon (block values spread back to months; nothing invented, just repeated)
    ribbon_p = np.repeat(occ / L, L)[:n]
    ribbon_p = np.r_[ribbon_p, np.full(n - len(ribbon_p), np.nan)]
    trend_y = np.repeat(np.asarray(tr.Y, float), L)[:n]
    trend_y = np.r_[trend_y, np.full(n - len(trend_y), np.nan)]

    for e in events:
        e.pop("k", None)
        e.pop("decimal_year", None)
    txt = _plain_language(events, p_no_change, phi, L, p_up, p_down, len(null_arr))
    return {
        "status": "ok",
        "method": ("BEAST Bayesian ensemble on memory-matched blocks, window probabilities, "
                   "AR(1) surrogate-calibrated change test"),
        "citation": CITATION,
        "memory": {"lag1_autocorr": phi, "block_months": L},
        "n_surrogates": int(len(null_arr)),
        "probability_no_change": p_no_change,
        "number_of_changes_probability": ncp_pr[:6],
        "events": events,
        "segments": segments,
        "current_direction_probability": {"rising": p_up, "flat": p_flat, "falling": p_down,
                                          "note": "posterior slope sign over the last year (model probability)"},
        "ribbon": {"time": [d.strftime("%Y-%m") for d in ms.time],
                   "change_probability": [None if not np.isfinite(x) else float(x) for x in ribbon_p],
                   "trend_anomaly": [None if not np.isfinite(x) else float(x) for x in trend_y]},
        "plain_language": txt,
        "limits": ["A change point is a date when the trend's behaviour changed, not its cause.",
                   "Persistent (autocorrelated) data hides changes; 'no confirmed change' is not proof of no change.",
                   "Dates are resolved to about one block of months; see interval90."],
    }


def _plain_language(events: list[dict], p0: float | None, phi: float, L: int, p_up: float, p_down: float,
                    k: int) -> str:
    conf = [e for e in events if e["status"] == "confirmed"]
    poss = [e for e in events if e["status"] == "possible"]
    parts = []
    if conf:
        for e in conf:
            kind = e.get("kind", "change")
            s = (f"The trend changed ({kind}) around {e['date']} "
                 f"(90% interval {e['interval90'][0]} to {e['interval90'][1]}; probability {e['probability']:.0%}). "
                 f"This change is stronger than in {round((1 - e['p_calibrated']) * (k + 1))} of {k} simulated "
                 f"series with the same noise and no change.")
            if "slope_before_per_decade" in e:
                s += (f" Rate before: {e['slope_before_per_decade']:+.3g}/decade; "
                      f"after: {e['slope_after_per_decade']:+.3g}/decade.")
            if e.get("near_seam"):
                s += (f" It falls near a known data seam ({e['near_seam']['date']}): possible instrument effect.")
            parts.append(s)
    elif poss:
        e = poss[0]
        parts.append(f"A possible change around {e['date']} (probability {e['probability']:.0%}) is not stronger "
                     f"than what persistent noise produces (calibrated p = {e['p_calibrated']:.2f}), so it is not "
                     f"confirmed.")
    else:
        parts.append("No change in the trend was found: one steady trend describes the record.")
    if phi >= 0.6:
        parts.append(f"The data are strongly persistent (lag-1 autocorrelation {phi:.2f}), which makes changes hard "
                     f"to date.")
    if max(p_up, p_down) >= 0.9:
        parts.append(f"Model probability that the trend is {'rising' if p_up > p_down else 'falling'} over the last "
                     f"year: {max(p_up, p_down):.0%}.")
    return " ".join(parts)
