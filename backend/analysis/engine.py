"""Analysis orchestration: monthly series -> deseasonalize -> tests -> verdict (contract §5)."""
from __future__ import annotations

import math

import numpy as np

from ..core.errors import InsufficientData
from ..timeseries.model import MonthlySeries
from .deseason import deseasonalize
from .trend import mann_kendall, ols_trend, seasonal_mann_kendall, sens_slope
from .verdict import build_verdict

METHODS_VERSION = "1.0.0"
ALL_METHODS = ("ols", "mk", "seasonal_mk", "sen")


def _clean(x):
    """JSON-safe: NaN/inf -> None, numpy scalars -> python."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return [_clean(v) for v in x.tolist()]
    if isinstance(x, (np.floating, float)):
        xf = float(x)
        return xf if math.isfinite(xf) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def analyze_series(
    ms: MonthlySeries,
    *,
    alpha: float = 0.05,
    deseasonalize_method: str = "stl",
    methods: tuple[str, ...] | list[str] = ALL_METHODS,
    mk_variant: str = "auto",
    min_months: int = 120,
    include_series: bool = True,
) -> dict:
    comp = ms.completeness()
    if comp["n_valid"] < 24:
        raise InsufficientData(
            f"Only {comp['n_valid']} valid months; at least 24 are needed to test a trend "
            f"(recommended: {min_months}).", detail={"completeness": comp})

    t = ms.t_years()
    years = float(t[np.isfinite(ms.value)][-1] - t[np.isfinite(ms.value)][0] + 1 / 12)
    des = deseasonalize(ms, deseasonalize_method)
    y = des.deseasonalized

    ols = ols_trend(t, y, alpha)
    r1 = ols.lag1_autocorr
    n_valid = ols.n
    autocorr_sig = r1 > 1.96 / math.sqrt(n_valid)
    # "auto" = MK with AR(1) effective-sample-size correction: calibrated false-positive rate for
    # 0 <= phi <= 0.85 (see docs/STATISTICS.md); reduces to the original test when r1 <= 0.
    variant = "ess_ar1" if mk_variant == "auto" else mk_variant
    mk = mann_kendall(t, y, alpha, variant)
    mk_orig = mk if variant == "original" else mann_kendall(t, y, alpha, "original")
    sen = sens_slope(t, y, alpha)

    smk = None
    if "seasonal_mk" in methods:
        years_idx = ms.time.year.to_numpy().astype(float)
        season = (ms.time.month.to_numpy() - 1).astype(np.int64)
        smk = seasonal_mann_kendall(years_idx, season, ms.value, 12, alpha)

    ols_d = ols.to_dict()
    sen_d = sen.to_dict()
    mk_d = mk.to_dict()
    smk_d = smk.to_dict() if smk else None

    verdict = build_verdict(
        ols=ols_d, mk=mk_d, smk=smk_d, sen=sen_d, units=ms.units, alpha=alpha, years=years,
        mean_level=float(np.nanmean(ms.value)), completeness=comp, min_months=min_months, label=ms.label,
    )
    verdict["notes"] = des.notes

    out = {
        "series_id": ms.series_id,
        "variable_id": ms.variable_id,
        "label": ms.label,
        "units": ms.units,
        "methods_version": METHODS_VERSION,
        "period": {"start": comp["start"], "end": comp["end"], "n_months": comp["n_months"],
                   "n_valid": comp["n_valid"], "missing_pct": comp["missing_pct"],
                   "longest_gap_months": comp["longest_gap_months"], "years": years},
        "deseasonalized": deseasonalize_method != "none",
        "deseasonalize_method": des.method,
        "seasonal_amplitude": des.seasonal_amplitude,
        "climatology": des.climatology,
        "ols": ols_d,
        "mann_kendall": mk_d,
        "mann_kendall_original": mk_orig.to_dict(),
        "seasonal_mk": smk_d,
        "sen": sen_d,
        "diagnostics": {
            "lag1_autocorr": r1,
            "lag1_significant": autocorr_sig,
            "durbin_watson": ols.durbin_watson,
            "n_eff": ols.n_eff,
            "mk_variance_correction": mk.variance_correction,
        },
        "verdict": verdict,
        "provenance": ms.provenance.to_dict(),
    }
    if include_series:
        trend_line = ols.intercept + ols.slope * t
        sen_line = sen.intercept + sen.slope * t
        out["chart"] = {
            "time": [d.strftime("%Y-%m-%d") for d in ms.time],
            "raw": ms.value,
            "deseasonalized": y,
            "seasonal": des.seasonal,
            "stl_trend": des.trend_component,
            "ols_line": trend_line,
            "sen_line": sen_line,
        }
    return _clean(out)
