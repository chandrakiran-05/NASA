"""Digital twin: a sandbox for engineers. Research data goes in directly (no verification gate),
and what-if scenarios run forward from it.

Each variable gets a baseline fitted from its own data: monthly climatology, a linear trend of the
anomalies (AR(1)-adjusted standard error) and AR(1) noise. A simulation continues that baseline from
the last observed month for `horizon_years`, in `n_runs` Monte Carlo runs, with the engineer's knobs:

  trend_multiplier / trend_add_per_decade   change the trend ("twice as fast", "+0.3 per decade")
  shocks [{year, size}]                     a step change from that year on
  drivers [{from, coefficient}]             couple to an earlier variable: y += k * (x - x's baseline)
  fit_since_year (year or "auto")           fit the trend only from that year ("auto": after the last PELT break)
  threshold {value, direction}              tipping level: probability and date of first crossing

Everything returned is labelled simulated. Nothing is written back into the observed series.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..analysis.deseason import monthly_climatology
from ..analysis.trend import lag1_autocorr, ols_trend
from ..insights.changepoint import detect_trend_breaks
from ..core.errors import InvalidRequest
from ..timeseries.model import MonthlySeries

DISCLAIMER = ("Simulation from the uploaded data and your scenario settings: not observations and not a climate "
              "projection. Trends and couplings are what you set; the model is linear trend + AR(1) noise.")


def baseline(ms: MonthlySeries, fit_since_year: int | str | None = None) -> dict:
    if ms.n_valid < 24:
        raise InvalidRequest(f"{ms.label}: needs at least 24 valid months to fit a baseline (has {ms.n_valid})")
    months = ms.time.month.to_numpy() - 1
    overall = float(np.nanmean(ms.value))
    clim = monthly_climatology(ms)
    clim = np.where(np.isfinite(clim), clim, overall)   # shortcut: never-observed months (annual data) use the mean
    anom = ms.value - clim[months]
    t = ms.t_years()
    if fit_since_year == "auto":                                 # trend only after the last detected break (PELT)
        br = detect_trend_breaks(ms.time, t, anom).get("breaks", [])
        fit_since_year = int(br[-1]["date"][:4]) if br else None
    fit = anom if fit_since_year is None else np.where(ms.time.year >= int(fit_since_year), anom, np.nan)
    if np.isfinite(fit).sum() < 24:
        raise InvalidRequest(f"{ms.label}: fit_since_year {fit_since_year} leaves fewer than 24 valid months")
    o = ols_trend(t, fit)
    resid = fit - (o.intercept + o.slope * t)
    last = int(np.flatnonzero(np.isfinite(ms.value))[-1])
    annual = len(set(months[np.isfinite(ms.value)])) == 1      # yearly research data, or one month per year
    # month-dependent noise SD (seasonal variance), pooled toward the overall SD when a month has few values
    sd_all = float(np.nanstd(resid))
    msd = np.full(12, sd_all)
    if not annual:
        for m in range(12):
            r = resid[months == m]
            k = np.isfinite(r).sum()
            if k >= 3:
                msd[m] = np.sqrt((np.nansum(r ** 2) + 5 * sd_all ** 2) / (k + 5))
    z = resid / msd[months]
    phi = lag1_autocorr(z[np.isfinite(z)] if annual else z)
    nz = int(np.isfinite(z).sum())
    phi = float(np.clip(phi, 0.0, 0.95))
    zf = z[np.isfinite(z)]
    innov = zf[1:] - phi * zf[:-1] if annual else (z[1:] - phi * z[:-1])
    innov = innov[np.isfinite(innov)]
    innov = innov / innov.std() if len(innov) > 2 and innov.std() > 0 else np.zeros(0)
    kurt = float(np.mean(innov ** 4)) - 3 if len(innov) else 0.0
    return {"n_valid": ms.n_valid, "start": ms.time[0].strftime("%Y-%m"), "last_observed": ms.time[last].strftime("%Y-%m"),
            "units": ms.units, "slope_per_decade": o.slope * 10, "slope_se_per_decade": o.se_adj * 10,
            "noise_sd": sd_all, "lag1_autocorr": phi,
            "frequency": "annual" if annual else "monthly",
            "_level": o.intercept + o.slope * t[last], "_resid": float(resid[last]), "_clim": clim,
            "_last": ms.time[last], "_msd": msd,
            "_pivot": float(t[last] - np.mean(t[np.isfinite(fit)])),
            "_level_se": sd_all * np.sqrt((1 + phi) / (1 - phi) / max(nz, 1)),
            "_innov": innov if kurt > 1.0 and len(innov) >= 30 else None}   # heavy tails: resample real innovations


def simulate(series: dict[str, MonthlySeries], scenario: dict, *, horizon_years: int = 30, n_runs: int = 500,
             seed: int = 2026, return_runs: bool = False) -> dict:
    unknown = set(scenario) - set(series)
    if unknown:
        raise InvalidRequest(f"Scenario names variables not in this twin: {sorted(unknown)}")
    rng = np.random.default_rng(seed)
    H = horizon_years * 12
    tau = np.arange(1, H + 1) / 12.0
    runs, paths, out = {}, {}, {}
    for name, ms in series.items():                     # upload order; drivers must come earlier
        sc = scenario.get(name, {})
        b = baseline(ms, sc.get("fit_since_year"))
        time = pd.date_range(b["_last"] + pd.offsets.MonthBegin(1), periods=H, freq="MS")
        slope = rng.normal(b["slope_per_decade"], b["slope_se_per_decade"], n_runs) / 10
        # slope error pivots at the fit's mean time, so it already offsets the level at the last month;
        # plus the error of the fitted mean itself
        level = b["_level"] + (slope - b["slope_per_decade"] / 10) * b["_pivot"] + rng.normal(0, b["_level_se"], n_runs)
        slope = slope * sc.get("trend_multiplier", 1.0) + sc.get("trend_add_per_decade", 0.0) / 10
        phi, sig = b["lag1_autocorr"], np.sqrt(1 - b["lag1_autocorr"] ** 2)
        msd = b["_msd"][time.month.to_numpy() - 1]
        keep = time.month == b["_last"].month if b["frequency"] == "annual" else np.ones(H, bool)
        noise = np.empty((n_runs, H))
        z0 = b["_resid"] / b["_msd"][b["_last"].month - 1]
        prev = np.full(n_runs, z0 if np.isfinite(z0) else 0.0)
        for k in range(H):
            if keep[k]:                                     # annual data: one AR(1) step per year, carried between
                e = rng.choice(b["_innov"], n_runs) if b["_innov"] is not None else rng.normal(0, 1, n_runs)
                prev = phi * prev + sig * e
            noise[:, k] = prev * msd[k]
        y = level[:, None] + slope[:, None] * tau + noise
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
        if return_runs:                      # internal: per-run matrix for compound events (not JSON)
            res["_runs"] = vals
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


def backtest(series: dict[str, MonthlySeries], *, holdout_years: int = 10, n_runs: int = 300, seed: int = 2026,
             scenario: dict | None = None) -> dict:
    """Hide the last `holdout_years`, simulate them from the earlier data, and score against what happened:
    coverage of the 5-95% band (should be ~90%) and mean absolute error of the median."""
    cut = {}
    for name, ms in series.items():
        k = len(ms.time) - holdout_years * 12
        if k < 24:
            raise InvalidRequest(f"{name}: too short to hold out {holdout_years} years")
        cut[name] = MonthlySeries(time=ms.time[:k], value=ms.value[:k], units=ms.units, provenance=ms.provenance,
                                  label=ms.label)
    sim = simulate(cut, scenario or {}, horizon_years=holdout_years, n_runs=n_runs, seed=seed)
    out = {}
    for name, ms in series.items():
        r = sim["variables"][name]
        obs = dict(zip(ms.time.strftime("%Y-%m"), ms.value))
        pairs = [(obs.get(t), lo, md, hi) for t, lo, md, hi in zip(r["time"], r["p05"], r["p50"], r["p95"])
                 if obs.get(t) is not None and np.isfinite(obs.get(t))]
        if not pairs:
            out[name] = {"status": "no_overlap"}
            continue
        o, lo, md, hi = map(np.array, zip(*pairs))
        cov = float(np.mean((o >= lo) & (o <= hi)))
        out[name] = {"months_scored": len(o), "band_coverage": cov, "target_coverage": 0.90,
                     "median_abs_error": float(np.mean(np.abs(o - md))), "units": ms.units,
                     "held_out": [r["time"][0], r["time"][-1]],
                     "plain_language": (f"Hiding {holdout_years} years and simulating them, {cov:.0%} of the real months "
                                        f"fell inside the 5-95% band (target about 90%)"
                                        + ("; the bands look too narrow." if cov < 0.8 else
                                           "; the bands look too wide." if cov > 0.97 else "."))}
    return {"holdout_years": holdout_years, "n_runs": n_runs, "seed": seed, "variables": out,
            "limit": "A backtest checks the baseline model only (no knobs); past skill does not guarantee future skill."}
