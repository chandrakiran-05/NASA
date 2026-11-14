"""F3 — Method Verdict / Trend Court.

Diagnostics choose the test and say why; all jurors are shown side by side; the "conclusion
flips" flag fires when they disagree; cross-examination re-runs the case under different
assumptions (seasonal cycle left in, autocorrelation ignored, shorter record).
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from ..analysis.deseason import deseasonalize
from ..analysis.trend import mann_kendall, ols_trend, seasonal_mann_kendall, sens_slope
from ..timeseries.model import MonthlySeries


def _jurors(t, y, ms: MonthlySeries | None, alpha: float) -> list[dict]:
    o = ols_trend(t, y, alpha)
    sen = sens_slope(t, y, alpha)
    out = [
        {"id": "ols_naive", "name": "Regression t-test (ignores persistence)", "p": o.p, "slope_per_decade": o.slope * 10,
         "accounts_for_autocorrelation": False},
        {"id": "ols_ar1", "name": "Regression t-test, AR(1)-adjusted", "p": o.p_adj, "slope_per_decade": o.slope * 10,
         "accounts_for_autocorrelation": True},
    ]
    for v, nm, ac in (("original", "Mann-Kendall (original)", False), ("tfpw", "Mann-Kendall, prewhitened (TFPW)", True),
                      ("hamed_rao", "Mann-Kendall, Hamed-Rao", True), ("ess_ar1", "Mann-Kendall, effective sample size", True)):
        r = mann_kendall(t, y, alpha, v)
        out.append({"id": f"mk_{v}", "name": nm, "p": r.p, "slope_per_decade": sen.slope * 10,
                    "accounts_for_autocorrelation": ac})
    if ms is not None:
        s = seasonal_mann_kendall(ms.time.year.to_numpy(), ms.time.month.to_numpy() - 1, ms.value, 12, alpha)
        out.append({"id": "seasonal_mk", "name": "Seasonal Mann-Kendall", "p": s.p,
                    "slope_per_decade": s.sen_slope * 10, "accounts_for_autocorrelation": False})
    sen_sig = not (sen.ci95[0] <= 0 <= sen.ci95[1])
    out.append({"id": "sen_ci", "name": "Sen's slope 95% CI excludes zero", "p": None, "significant": sen_sig,
                "slope_per_decade": sen.slope * 10, "ci95_per_decade": [sen.ci95[0] * 10, sen.ci95[1] * 10],
                "accounts_for_autocorrelation": False})
    for j in out:
        if "significant" not in j:
            j["significant"] = bool(j["p"] is not None and j["p"] < alpha)
    return out


def court(ms: MonthlySeries, alpha: float = 0.05) -> dict:
    t = ms.t_years()
    des = deseasonalize(ms, "stl").deseasonalized
    valid = np.isfinite(ms.value)

    # ---- diagnostics
    o = ols_trend(t, des, alpha)
    r1 = o.lag1_autocorr
    r1_sig = r1 > 1.96 / math.sqrt(o.n)
    groups = [ms.value[(ms.time.month == m) & valid] for m in range(1, 13)]
    groups = [g for g in groups if len(g) >= 2]
    kw = stats.kruskal(*groups) if len(groups) >= 2 else None
    seasonal = bool(kw is not None and kw.pvalue < alpha)
    ties = 1 - len(np.unique(ms.value[valid])) / max(valid.sum(), 1)

    if seasonal and r1_sig:
        chosen, reason = "mk_ess_ar1", ("The data have a seasonal cycle (removed with STL) and month-to-month "
                                        "persistence, so we use Mann-Kendall with an effective-sample-size correction "
                                        "and the AR(1)-adjusted regression.")
    elif r1_sig:
        chosen, reason = "mk_ess_ar1", "Months are persistent (lag-1 autocorrelation is significant), so the test is corrected for it."
    elif seasonal:
        chosen, reason = "seasonal_mk", "There is a seasonal cycle and no strong persistence, so Seasonal Mann-Kendall fits best."
    else:
        chosen, reason = "mk_original", "No seasonal cycle or persistence detected, so the original Mann-Kendall test is appropriate."

    jurors = _jurors(t, des, ms, alpha)
    by_id = {j["id"]: j for j in jurors}
    verdict_sig = by_id["mk_ess_ar1"]["significant"] and by_id["ols_ar1"]["significant"]   # same pair as the result card
    n_sig = sum(j["significant"] for j in jurors)
    flips = 0 < n_sig < len(jurors)

    consistency = []
    sen = by_id["sen_ci"]
    if abs(sen["slope_per_decade"]) < 1e-12 and any(j["significant"] for j in jurors if j["id"].startswith("mk")):
        consistency.append("Mann-Kendall is significant but Sen's slope is 0: many tied values. Report the trend as "
                           "'present but too small to measure at this resolution'.")
    if ties > 0.2:
        consistency.append(f"{ties:.0%} of values are tied (rounded data); rank tests lose power.")
    naive_only = [j["name"] for j in jurors if j["significant"] and not j["accounts_for_autocorrelation"]
                  and j["id"] not in ("seasonal_mk", "sen_ci")]
    if naive_only and not verdict_sig:
        consistency.append("Only tests that ignore persistence call it significant. This is how papers overclaim.")

    # ---- cross-examination
    cross = []
    raw_j = {j["id"]: j for j in _jurors(t, ms.value, None, alpha)}
    cross.append({"id": "seasonal_cycle_left_in", "question": "What if we forget to remove the seasonal cycle?",
                  "significant": raw_j["ols_ar1"]["significant"] and raw_j["mk_ess_ar1"]["significant"],
                  "p": max(raw_j["ols_ar1"]["p"], raw_j["mk_ess_ar1"]["p"])})
    cross.append({"id": "ignore_autocorrelation", "question": "What if we ignore month-to-month persistence?",
                  "significant": by_id["ols_naive"]["significant"] and by_id["mk_original"]["significant"],
                  "p": max(by_id["ols_naive"]["p"], by_id["mk_original"]["p"])})
    n = len(ms.value)
    cut = n // 3
    if n - cut >= 60:
        o2 = ols_trend(t[cut:], des[cut:], alpha)
        m2 = mann_kendall(t[cut:], des[cut:], alpha, "ess_ar1")
        cross.append({"id": "shorter_record", "question": f"What if the record started in {ms.time[cut].year}?",
                      "significant": o2.p_adj < alpha and m2.p < alpha, "p": max(o2.p_adj, m2.p),
                      "slope_per_decade": o2.slope * 10})
    for c in cross:
        c["flips_verdict"] = c["significant"] != verdict_sig

    stamp = "SIGNIFICANT" if verdict_sig else "NOT PROVEN"
    return {
        "stamp": stamp,
        "chosen_test": chosen, "reason": reason,
        "diagnostics": {"lag1_autocorr": r1, "lag1_significant": bool(r1_sig),
                        "seasonality_kruskal_p": float(kw.pvalue) if kw is not None else None,
                        "seasonal": seasonal, "tied_fraction": float(ties)},
        "jurors": jurors, "jurors_significant": n_sig, "flips": flips,
        "consistency": consistency, "cross_examination": cross,
        "plain_language": (f"{stamp}. {reason} {n_sig} of {len(jurors)} tests call it significant"
                           + (" — the tests disagree, see why below." if flips else ".")),
        "limit": "Agreement between tests is not proof of a trend; it only shows the result does not hinge on one method.",
    }
