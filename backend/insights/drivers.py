"""Driver hints — "which other variable moves with this one, and how much of the trend could it explain?"

The challenge stresses relating trends to the processes that cause them. For a target series
and one or more candidate drivers over the same region:

1. Both series are deseasonalized and DETRENDED, so a shared trend cannot create a spurious
   correlation; only year-to-year co-variability is used.
2. Lagged correlation (lags 0..max_lag months, driver leading) with an effective sample size
   n_eff = n (1 - r1x r1y) / (1 + r1x r1y)  (Bretherton et al. 1999) and FDR across lags/drivers.
3. Sensitivity beta = d target / d driver from the detrended anomalies at the best lag.
4. Trend share = beta * driver_trend / target_trend: the part of the target trend that is
   *consistent with* the driver's trend if the year-to-year sensitivity also holds long-term.

This is evidence of association, not proof of causation; every response says so.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from ..analysis.deseason import deseasonalize
from ..analysis.trend import lag1_autocorr, ols_trend
from ..timeseries.model import MonthlySeries


def _detrended_anoms(ms: MonthlySeries) -> tuple[pd.Series, float, float]:
    des = deseasonalize(ms, "climatology").deseasonalized
    t = ms.t_years()
    o = ols_trend(t, des)
    resid = des - (o.intercept + o.slope * t)
    return pd.Series(resid, index=ms.time), o.slope, o.p_adj


def driver_analysis(target: MonthlySeries, drivers: list[MonthlySeries], *, max_lag: int = 6,
                    alpha: float = 0.05) -> dict:
    tgt, tgt_slope, tgt_p = _detrended_anoms(target)
    rows = []
    for d in drivers:
        drv, drv_slope, drv_p = _detrended_anoms(d)
        best = None
        lag_rows = []
        for lag in range(0, max_lag + 1):
            x = drv.shift(lag, freq="MS")
            df = pd.concat([tgt.rename("y"), x.rename("x")], axis=1, join="inner").dropna()
            n = len(df)
            if n < 36:
                continue
            r = float(np.corrcoef(df["x"], df["y"])[0, 1])
            rx = max(lag1_autocorr(df["x"].to_numpy()), 0.0)
            ry = max(lag1_autocorr(df["y"].to_numpy()), 0.0)
            neff = max(n * (1 - rx * ry) / (1 + rx * ry), 5.0)
            tstat = r * math.sqrt((neff - 2) / max(1 - r * r, 1e-12))
            p = float(2 * stats.t.sf(abs(tstat), neff - 2))
            beta = float(np.polyfit(df["x"], df["y"], 1)[0])
            row = {"lag_months": lag, "r": r, "n": n, "n_eff": neff, "p": p, "beta": beta}
            lag_rows.append(row)
            if best is None or abs(r) > abs(best["r"]):
                best = row
        if best is None:
            rows.append({"driver": d.label or d.variable_id, "status": "insufficient_overlap"})
            continue
        share = best["beta"] * drv_slope / tgt_slope if tgt_slope != 0 else None
        rows.append({
            "driver": d.label or d.variable_id, "driver_series_id": d.series_id, "driver_units": d.units,
            "best_lag_months": best["lag_months"], "r": best["r"], "p": best["p"], "n_eff": best["n_eff"],
            "sensitivity": best["beta"],
            "sensitivity_units": f"{target.units or ''} per {d.units or 'unit'}",
            "driver_trend_per_decade": drv_slope * 10, "driver_trend_p": drv_p,
            "trend_share": share, "lags": lag_rows,
        })

    tested = [r for r in rows if "p" in r]
    if tested:
        rej, pf, _, _ = multipletests([r["p"] for r in tested], alpha=alpha, method="fdr_bh")
        for r, q, s in zip(tested, pf, rej):
            r["p_fdr"] = float(q)
            r["significant_fdr"] = bool(s)
    tested.sort(key=lambda r: abs(r["r"]), reverse=True)

    lines = []
    for r in tested[:3]:
        if not r.get("significant_fdr"):
            continue
        share = r.get("trend_share")
        s_txt = ""
        if share is not None and math.isfinite(share) and r["driver_trend_p"] < alpha:
            s_txt = f"; its own trend could account for roughly {max(min(share, 9.99), -9.99) * 100:.0f}% of the target trend"
        lag_txt = "at the same time" if r["best_lag_months"] == 0 else f"{r['best_lag_months']} month(s) later"
        lines.append(f"{r['driver']} co-varies with the target {lag_txt} (r = {r['r']:.2f}){s_txt}")
    txt = ("; ".join(lines) + ". These are associations, not proof of cause.") if lines else \
        "None of the candidate drivers co-varies significantly with the target after removing trends and seasons."
    return {
        "method": "detrended-anomaly lagged correlation, Bretherton n_eff, BH-FDR, sensitivity x driver trend",
        "target": target.label or target.variable_id,
        "target_trend_per_decade": tgt_slope * 10, "target_trend_p": tgt_p,
        "drivers": rows,
        "plain_language": txt,
        "disclaimer": "Correlation of detrended anomalies indicates association, not causation.",
    }
