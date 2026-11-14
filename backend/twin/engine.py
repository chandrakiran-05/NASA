"""Digital twin: a sandbox for engineers. Research data goes in directly (no verification gate),
and what-if scenarios run forward from it.

Each variable gets a baseline fitted from its own data: monthly climatology, a linear trend of the
anomalies (AR(1)-adjusted standard error) and AR(1) noise. A simulation continues that baseline from
the last observed month for `horizon_years`, in `n_runs` Monte Carlo runs, with the engineer's knobs:

  trend_multiplier / trend_add_per_decade   change the trend ("twice as fast", "+0.3 per decade")
  shocks [{year, size}]                     a step change from that year on
  drivers [{from, coefficient}]             couple to an earlier variable: y += k * (x - x's baseline)
  threshold {value, direction}              tipping level: probability and date of first crossing

Everything returned is labelled simulated. Nothing is written back into the observed series.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..analysis.deseason import monthly_climatology
from ..analysis.trend import lag1_autocorr, ols_trend
from ..core.errors import InvalidRequest
from ..timeseries.model import MonthlySeries

DISCLAIMER = ("Simulation from the uploaded data and your scenario settings: not observations and not a climate "
              "projection. Trends and couplings are what you set; the model is linear trend + AR(1) noise.")


def baseline(ms: MonthlySeries) -> dict:
    if ms.n_valid < 24:
        raise InvalidRequest(f"{ms.label}: needs at least 24 valid months to fit a baseline (has {ms.n_valid})")
    months = ms.time.month.to_numpy() - 1
    overall = float(np.nanmean(ms.value))
    clim = monthly_climatology(ms)
    clim = np.where(np.isfinite(clim), clim, overall)   # shortcut: never-observed months (annual data) use the mean
    anom = ms.value - clim[months]
    t = ms.t_years()
    o = ols_trend(t, anom)
    resid = anom - (o.intercept + o.slope * t)
    last = int(np.flatnonzero(np.isfinite(ms.value))[-1])
    annual = len(set(months[np.isfinite(ms.value)])) == 1      # yearly research data, or one month per year
    phi = lag1_autocorr(resid[np.isfinite(resid)] if annual else resid)
    return {"n_valid": ms.n_valid, "start": ms.time[0].strftime("%Y-%m"), "last_observed": ms.time[last].strftime("%Y-%m"),
            "units": ms.units, "slope_per_decade": o.slope * 10, "slope_se_per_decade": o.se_adj * 10,
            "noise_sd": float(np.nanstd(resid)), "lag1_autocorr": float(np.clip(phi, 0.0, 0.95)),
            "frequency": "annual" if annual else "monthly",
            "_level": o.intercept + o.slope * t[last], "_resid": float(resid[last]), "_clim": clim,
            "_last": ms.time[last]}


def simulate(series: dict[str, MonthlySeries], scenario: dict, *, horizon_years: int = 30, n_runs: int = 500,
             seed: int = 2026) -> dict:
    unknown = set(scenario) - set(series)
    if unknown:
        raise InvalidRequest(f"Scenario names variables not in this twin: {sorted(unknown)}")
    rng = np.random.default_rng(seed)
    H = horizon_years * 12
    tau = np.arange(1, H + 1) / 12.0
    runs, paths, out = {}, {}, {}
    for name, ms in series.items():                     # upload order; drivers must come earlier
        b = baseline(ms)
        sc = scenario.get(name, {})
        time = pd.date_range(b["_last"] + pd.offsets.MonthBegin(1), periods=H, freq="MS")
        slope = rng.normal(b["slope_per_decade"], b["slope_se_per_decade"], n_runs) / 10
        slope = slope * sc.get("trend_multiplier", 1.0) + sc.get("trend_add_per_decade", 0.0) / 10
        phi, sig = b["lag1_autocorr"], b["noise_sd"] * np.sqrt(1 - b["lag1_autocorr"] ** 2)
        keep = time.month == b["_last"].month if b["frequency"] == "annual" else np.ones(H, bool)
        noise = np.empty((n_runs, H))
        prev = np.full(n_runs, b["_resid"] if np.isfinite(b["_resid"]) else 0.0)
        for k in range(H):
            if keep[k]:                                     # annual data: one AR(1) step per year, carried between
                prev = phi * prev + rng.normal(0, sig, n_runs)
            noise[:, k] = prev
        y = b["_level"] + slope[:, None] * tau + noise
        for s in sc.get("shocks", []):
            y[:, time.year >= int(s["year"])] += float(s["size"])
        for d in sc.get("drivers", []):
            src = d["from"]
            if src not in runs:
                raise InvalidRequest(f"{name}: driver {src!r} must be a variable uploaded before {name!r}")
            y += float(d["coefficient"]) * (runs[src] - paths[src])
        base_path = b["_level"] + b["slope_per_decade"] / 10 * tau  # no noise, no scenario: drivers' reference
        runs[name], paths[name] = y, base_path
        vals = (y + b["_clim"][time.month.to_numpy() - 1])[:, keep]
        out_time = time[keep]
        p05, p50, p95 = np.percentile(vals, [5, 50, 95], axis=0)
        res = {"baseline": {k: v for k, v in b.items() if not k.startswith("_")}, "scenario": sc,
               "time": [d.strftime("%Y-%m") for d in out_time],
               "p05": p05.round(6).tolist(), "p50": p50.round(6).tolist(), "p95": p95.round(6).tolist(),
               "label": "simulated"}
        th = sc.get("threshold")
        if th:
            hit = vals >= th["value"] if th.get("direction", "above") == "above" else vals <= th["value"]
            any_hit = hit.any(axis=1)
            first = np.where(any_hit, hit.argmax(axis=1), -1)
            when = sorted(out_time[first[any_hit]])
            yr = np.where(any_hit, out_time.year.to_numpy()[np.maximum(first, 0)], 10 ** 6)
            curve = [{"year": int(Y), "p": float((yr <= Y).mean())} for Y in sorted(set(out_time.year))]
            res["threshold"] = {**th, "probability_by_end": float(any_hit.mean()), "probability_by_year": curve,
                                "median_first_crossing": when[len(when) // 2].strftime("%Y-%m") if when else None,
                                "earliest_10pct": when[len(when) // 10].strftime("%Y-%m") if when else None,
                                "plain_language": (f"In {any_hit.mean():.0%} of {n_runs} simulated runs {name} crosses "
                                                   f"{th['value']} {ms.units or ''} by {out_time[-1].year}"
                                                   + (f"; half of those cross by {when[len(when) // 2].year}." if when else "."))}
        out[name] = res
    return {"horizon_years": horizon_years, "n_runs": n_runs, "seed": seed, "variables": out,
            "disclaimer": DISCLAIMER}


def simulate_compare(series: dict[str, MonthlySeries], scenario: dict, **kw) -> dict:
    """Scenario next to a reference run that keeps only the thresholds. Knobs draw no random numbers, so with
    the same seed both runs share the same noise and differ only by the knobs."""
    res = simulate(series, scenario, **kw)
    ref = simulate(series, {k: {"threshold": v["threshold"]} for k, v in scenario.items() if v.get("threshold")}, **kw)
    for name, r in res["variables"].items():
        rr = ref["variables"][name]
        r["reference"] = {"label": "simulated reference (no knobs)", "p05": rr["p05"], "p50": rr["p50"],
                          "p95": rr["p95"], "threshold": rr.get("threshold")}
        r["delta_p50"] = [round(a - b, 6) for a, b in zip(r["p50"], rr["p50"])]
    return res
