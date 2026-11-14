"""Runs the novel-insight models on one monthly series and assembles the
Trend Evidence Index (TEI), a transparent 0-100 summary of how well-supported a trend is.

TEI components (each 0..1, weights in brackets):
  significance  [0.35]  OLS(AR1-adjusted) + Mann-Kendall agreement
  robustness    [0.25]  share of all >=10-yr windows that are significant with the same sign
  detectability [0.15]  record length / years needed (Weatherhead 1998)
  emergence     [0.15]  current signal-to-noise / 2
  records       [0.10]  excess of record highs (rising) or lows (falling) vs. no-trend expectation
"""
from __future__ import annotations

import math
import time as _time

import numpy as np

from ..analysis.deseason import deseasonalize
from ..analysis.engine import _clean
from ..analysis.trend import mann_kendall, ols_trend
from ..timeseries.model import MonthlySeries
from .changepoint import detect_trend_breaks
from .detectability import detectability
from .emergence import record_statistics, time_of_emergence
from .forecast import forecast_ensemble
from .triangle import trend_triangle

ALL_INSIGHTS = ("detectability", "emergence", "records", "breaks", "triangle", "forecast", "onset")
TEI_WEIGHTS = {"significance": 0.35, "robustness": 0.25, "detectability": 0.15, "emergence": 0.15, "records": 0.10}


def _tei(components: dict) -> dict:
    used = {k: v for k, v in components.items() if v is not None}
    if not used:
        return {"score": None}
    wsum = sum(TEI_WEIGHTS[k] for k in used)
    score = 100.0 * sum(TEI_WEIGHTS[k] * used[k] for k in used) / wsum
    if score >= 75:
        label = "Confirmed trend"
    elif score >= 50:
        label = "Likely trend"
    elif score >= 25:
        label = "Emerging or uncertain"
    else:
        label = "No trend detected"
    return {"score": round(score, 1), "label": label, "components": components, "weights": TEI_WEIGHTS}


def run_insights(ms: MonthlySeries, *, which: tuple[str, ...] | list[str] = ALL_INSIGHTS, alpha: float = 0.05,
                 deseasonalize_method: str = "stl", forecast_horizon: int = 60, triangle_min_years: int = 10,
                 min_segment_years: float = 4.0) -> dict:
    timings = {}
    t0 = _time.perf_counter()
    des = deseasonalize(ms, deseasonalize_method)
    y = des.deseasonalized
    t = ms.t_years()
    ols = ols_trend(t, y, alpha)
    mk = mann_kendall(t, y, alpha, "ess_ar1")
    valid_t = t[np.isfinite(y)]
    record_years = float(valid_t[-1] - valid_t[0] + 1 / 12)
    start_year = ms.time[0].year + (ms.time[0].month - 1) / 12 + float(valid_t[0])   # first month WITH data
    timings["base"] = _time.perf_counter() - t0
    out: dict = {"series_id": ms.series_id, "label": ms.label, "units": ms.units}

    def timed(name, fn):
        s = _time.perf_counter()
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 - one failing insight must not sink the rest
            out[name] = {"status": "error", "error": str(exc)}
        timings[name] = _time.perf_counter() - s

    if "detectability" in which:
        timed("detectability", lambda: detectability(ols.slope, ols.residuals, record_years, start_year,
                                                     phi=ols.lag1_autocorr))
    if "emergence" in which:
        timed("emergence", lambda: time_of_emergence(ms.time, y, ols.slope))
    if "records" in which:
        timed("records", lambda: record_statistics(ms.time, y))
    if "breaks" in which:
        timed("breaks", lambda: detect_trend_breaks(ms.time, t, y, min_segment_years=min_segment_years, alpha=alpha))
    if "triangle" in which:
        timed("triangle", lambda: trend_triangle(ms.time, t, y, min_years=triangle_min_years,
                                                 lag1=ols.lag1_autocorr, alpha=alpha))
    if "forecast" in which:
        timed("forecast", lambda: forecast_ensemble(ms.time, ms.value, horizon=forecast_horizon))
    if "onset" in which:
        from ..novelty.integrity import events_for
        from .onset import change_onset
        pelt = out.get("breaks", {}).get("breaks") if isinstance(out.get("breaks"), dict) else None
        timed("onset", lambda: change_onset(ms, seams=events_for(ms), pelt_breaks=pelt, alpha=alpha))

    # ---- Trend Evidence Index ----
    both = max(ols.p_adj, mk.p)
    one = min(ols.p_adj, mk.p)
    sig = 1.0 if both < 0.01 else 0.75 if both < alpha else 0.4 if one < alpha else 0.15 if one < 0.1 else 0.0
    comp = {"significance": sig, "robustness": None, "detectability": None, "emergence": None, "records": None}
    tri = out.get("triangle", {})
    if isinstance(tri, dict) and "fraction_significant_same_sign" in tri:
        comp["robustness"] = float(tri["fraction_significant_same_sign"])
    det = out.get("detectability", {})
    if isinstance(det, dict) and det.get("years_needed"):
        comp["detectability"] = float(min(1.0, record_years / det["years_needed"]))
    em = out.get("emergence", {})
    if isinstance(em, dict) and em.get("signal_to_noise_now") is not None:
        comp["emergence"] = float(min(1.0, em["signal_to_noise_now"] / 2.0))
    rec = out.get("records", {})
    if isinstance(rec, dict) and "p_highs" in rec:
        p_rec = rec["p_highs"] if ols.slope > 0 else rec["p_lows"]
        comp["records"] = 1.0 if p_rec < 0.05 else 0.5 if p_rec < 0.2 else 0.0
    out["trend_evidence_index"] = _tei(comp)
    out["timings_ms"] = {k: round(v * 1000, 1) for k, v in timings.items()}
    return _clean(out)
