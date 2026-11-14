"""Turns raw test numbers into the result card: direction, rate, total change,
significance in plain language, test agreement and caveats.

The wording is deterministic (no LLM) so the core result is always reproducible; the
offline AI may *rephrase* it, but its numbers are fact-checked against this output.
"""
from __future__ import annotations

import math

TEMPERATURE_UNITS = {"k", "kelvin", "degc", "°c", "c", "celsius", "deg c", "degrees c", "degf", "°f"}


def sig_round(x: float, sig: int = 3) -> float:
    if x is None or not math.isfinite(x) or x == 0:
        return x
    return round(x, sig - int(math.floor(math.log10(abs(x)))) - 1)


def fmt(x: float, sig: int = 3) -> str:
    if x is None or not math.isfinite(x):
        return "n/a"
    ax = abs(x)
    if ax != 0 and (ax >= 1e5 or ax < 1e-3):
        return f"{x:.{sig - 1}e}"
    v = sig_round(x, sig)
    s = f"{v:,.{max(sig - 1 - int(math.floor(math.log10(abs(v)))) if v else 0, 0)}f}"
    return s


def display_units(units: str | None) -> tuple[str, bool]:
    """Returns (unit label for *changes*, is_temperature). Kelvin differences equal °C differences."""
    if not units:
        return "", False
    u = units.strip()
    if u.lower() in TEMPERATURE_UNITS:
        if u.lower() in ("k", "kelvin"):
            return "°C (same as K for changes)", True
        return u, True
    return u, False


def describe_p(p: float, alpha: float) -> str:
    if p is None or not math.isfinite(p):
        return "significance could not be computed"
    if p < 0.001:
        return "very unlikely to be random chance (p < 0.001)"
    if p < 0.01:
        return f"unlikely to be random chance (p = {p:.3f})"
    if p < alpha:
        return f"probably not random chance (p = {p:.3f})"
    if p < 0.1:
        return f"suggestive, but not significant at the {int(alpha * 100)}% level (p = {p:.2f})"
    return f"could easily be natural variability (p = {p:.2f})"


def build_verdict(*, ols: dict, mk: dict, smk: dict | None, sen: dict, units: str | None,
                  alpha: float, years: float, mean_level: float, completeness: dict,
                  min_months: int, label: str | None = None) -> dict:
    unit_lbl, is_temp = display_units(units)
    unit_short = "°C" if (units or "").strip().lower() in ("k", "kelvin") else (units or "")

    tests = {
        "ols_ar1_adjusted": ols["p_adj"] < alpha,
        f"mann_kendall_{mk['variant']}": mk["p"] < alpha,
    }
    if smk is not None and smk.get("p") is not None:
        tests["seasonal_mann_kendall"] = smk["p"] < alpha

    sign_ols = math.copysign(1, ols["slope"]) if ols["slope"] != 0 else 0
    sign_sen = math.copysign(1, sen["slope"]) if sen["slope"] != 0 else 0
    same_direction = sign_ols == sign_sen
    n_sig = sum(tests.values())
    core_sig = tests["ols_ar1_adjusted"] and tests[f"mann_kendall_{mk['variant']}"]
    tests_agree = same_direction and (n_sig == len(tests) or n_sig == 0)

    if core_sig and same_direction:
        strength = "strong" if n_sig == len(tests) and max(ols["p_adj"], mk["p"]) < 0.01 else "moderate"
        significant = True
    elif n_sig > 0:
        strength = "mixed"
        significant = False
    else:
        strength = "none"
        significant = False

    rate = sen["slope_per_decade"]          # robust rate is the headline number
    total = sen["slope"] * years
    direction = "rising" if rate > 0 else ("falling" if rate < 0 else "flat")
    arrow = "↑" if rate > 0 else ("↓" if rate < 0 else "→")
    p_head = max(ols["p_adj"], mk["p"])

    rel = None
    if not is_temp and mean_level and math.isfinite(mean_level) and abs(mean_level) > 1e-12 and mean_level > 0:
        rel = 100.0 * total / mean_level

    subject = label or "This variable"
    rate_txt = f"{fmt(abs(rate))} {unit_short} per decade".strip()
    total_txt = f"{fmt(total)} {unit_short}".strip()
    if significant:
        head = f"{subject} is {direction} by about {rate_txt}; this is {describe_p(p_head, alpha)}."
    elif strength == "mixed":
        head = (f"{subject} shows a possible {direction} trend of about {rate_txt}, but the tests disagree "
                f"(regression p = {ols['p_adj']:.3f}, Mann-Kendall p = {mk['p']:.3f}).")
    else:
        head = (f"No significant trend: the estimated change of {rate_txt} {describe_p(p_head, alpha)}.")
    detail = (f"Over {fmt(years, 3)} years the fitted change is {total_txt}"
              + (f" ({fmt(rel, 2)}% of the average level)." if rel is not None else "."))

    caveats = []
    n_valid = completeness.get("n_valid", 0)
    if n_valid < min_months:
        caveats.append(f"Short record: {n_valid} valid months (< {min_months}). Treat the result as preliminary.")
    if completeness.get("missing_pct", 0) > 20:
        caveats.append(f"{completeness['missing_pct']}% of months are missing.")
    if completeness.get("longest_gap_months", 0) >= 12:
        caveats.append(f"Longest gap is {completeness['longest_gap_months']} months.")
    if ols["lag1_autocorr"] > 0.3:
        caveats.append(f"Strong month-to-month persistence (lag-1 r = {ols['lag1_autocorr']:.2f}); "
                       "p-values were corrected for it, which makes the test stricter.")
    if not same_direction:
        caveats.append("Regression and Sen slopes point in different directions: the trend is not robust.")
    if ols["r2"] < 0.05 and significant:
        caveats.append("The trend explains little of the month-to-month variation; it is small relative to the noise.")

    return {
        "direction": direction,
        "arrow": arrow,
        "significant": significant,
        "strength": strength,
        "alpha": alpha,
        "tests_agree": tests_agree,
        "tests_significant": tests,
        "rate_per_decade": rate,
        "rate_units": f"{unit_short}/decade".strip("/") if unit_short else "per decade",
        "total_change": total,
        "relative_change_pct": rel,
        "period_years": years,
        "headline_p": p_head,
        "plain_language": head + " " + detail,
        "caveats": caveats,
        "unit_note": unit_lbl if is_temp else None,
    }
