"""Detectability horizon — "how many years until this trend is provably real?"

The challenge notes: *"Sometimes all a trend needs to become significant is a longer period."*
This module quantifies exactly that with Weatherhead et al. (1998, JGR 103(D14)):

    n* = [ (3.3 * sigma_N / |omega_0|) * sqrt((1 + phi) / (1 - phi)) ] ** (2/3)      [years]

n*  : years of monthly data needed to detect a trend omega_0 (units/yr) with 90% probability
      at the 5% significance level, given monthly noise sd sigma_N and lag-1 autocorrelation phi.
95% bounds on n*:  n* * exp(+-B),  B = 4 / (3 sqrt(n*)) * sqrt((1+phi)/(1-phi)).

Inverting gives the minimum trend detectable with the record we already have.
"""
from __future__ import annotations

import math

import numpy as np


def detectability(slope_per_year: float, resid: np.ndarray, record_years: float, start_year: float,
                  phi: float | None = None) -> dict:
    r = np.asarray(resid, float)
    r = r[np.isfinite(r)]
    sigma = float(np.std(r, ddof=1)) if len(r) > 2 else float("nan")
    if phi is None:
        a, b = r[:-1], r[1:]
        phi = float(np.corrcoef(a, b)[0, 1]) if len(r) > 3 else 0.0
    phi_c = float(min(max(phi, 0.0), 0.95))
    infl = math.sqrt((1 + phi_c) / (1 - phi_c))

    out: dict = {
        "method": "Weatherhead et al. (1998)",
        "noise_sd_monthly": sigma,
        "noise_lag1_autocorr": phi_c,
        "record_years": record_years,
        "assumptions": "linear trend, AR(1) monthly noise, 90% detection probability at 5% significance",
    }
    # smallest trend detectable with the current record
    if record_years > 0 and math.isfinite(sigma):
        omega_min = 3.3 * sigma * infl / (record_years ** 1.5)
        out["min_detectable_trend_per_decade"] = omega_min * 10.0

    if not math.isfinite(sigma) or slope_per_year == 0 or not math.isfinite(slope_per_year):
        out.update({"years_needed": None, "status": "undefined", "plain_language":
                    "The trend is zero, so no record length would detect it."})
        return out

    n_star = ((3.3 * sigma / abs(slope_per_year)) * infl) ** (2.0 / 3.0)
    B = 4.0 / (3.0 * math.sqrt(n_star)) * infl
    lo, hi = n_star * math.exp(-B), n_star * math.exp(B)
    remaining = max(0.0, n_star - record_years)
    out.update({
        "years_needed": n_star,
        "years_needed_95ci": [lo, hi],
        "years_remaining": remaining,
        "expected_detection_year": start_year + n_star,
        "detectable_now": record_years >= n_star,
        "status": "detectable" if record_years >= n_star else "needs_more_data",
    })
    if record_years >= n_star:
        out["plain_language"] = (
            f"A trend of this size needs about {n_star:.0f} years of data to be detected reliably, "
            f"and this record already has {record_years:.0f}."
        )
    else:
        out["plain_language"] = (
            f"If the current rate continues, about {n_star:.0f} years of data (likely range {lo:.0f}–{hi:.0f}) "
            f"are needed to detect it reliably: roughly {remaining:.0f} more years, around "
            f"{start_year + n_star:.0f}."
        )
    return out
