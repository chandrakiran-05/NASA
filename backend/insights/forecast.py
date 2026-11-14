"""Short-range statistical projection with honest uncertainty.

Ensemble of fast, well-understood models:
  * snaive        seasonal naive (the benchmark every model must beat)
  * harmonic_ar1  linear trend + 2 annual harmonics, AR(1) errors (closed form, ~1 ms)
  * ets_damped    Holt-Winters additive, damped trend (statsmodels)
  * theta         Theta method with deseasonalisation (Assimakopoulos & Nikolopoulos 2000)

Model weights come from rolling-origin cross-validation (MASE); prediction bands are
split-conformal (empirical CV errors, distribution-free) plus a trend-uncertainty cone that
widens linearly with lead time from the AR(1)-adjusted slope standard error.

This is a statistical extrapolation of the observed record, NOT a climate-model projection;
the API says so in every response.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from ..analysis.trend import lag1_autocorr


def _fill_for_fit(time: pd.DatetimeIndex, y: np.ndarray) -> tuple[np.ndarray, int]:
    y = np.asarray(y, float)
    gaps = ~np.isfinite(y)
    if not gaps.any():
        return y.copy(), 0
    months = time.month.to_numpy() - 1
    clim = np.array([np.nanmean(y[months == m]) if np.isfinite(y[months == m]).any() else np.nanmean(y)
                     for m in range(12)])
    anom = pd.Series(y - clim[months]).interpolate(limit_direction="both").to_numpy()
    out = y.copy()
    out[gaps] = (anom + clim[months])[gaps]
    return out, int(gaps.sum())


def _design(t: np.ndarray, month0: np.ndarray, k: int = 2) -> np.ndarray:
    cols = [np.ones_like(t), t]
    for h in range(1, k + 1):
        ang = 2 * np.pi * h * month0 / 12.0
        cols += [np.cos(ang), np.sin(ang)]
    return np.column_stack(cols)


# ------------------------------- individual models ------------------------------------
def f_snaive(y: np.ndarray, h: int, **_) -> np.ndarray:
    last = y[-12:]
    return np.array([last[i % 12] for i in range(h)])


def f_harmonic_ar1(y: np.ndarray, h: int, *, t: np.ndarray, month0: np.ndarray, t_f: np.ndarray,
                   month0_f: np.ndarray, **_) -> np.ndarray:
    X = _design(t, month0)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ beta
    phi = float(np.clip(np.corrcoef(e[:-1], e[1:])[0, 1], -0.95, 0.95)) if len(e) > 3 else 0.0
    det = _design(t_f, month0_f) @ beta
    return det + e[-1] * phi ** np.arange(1, h + 1)


def f_ets_damped(y: np.ndarray, h: int, **_) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = ExponentialSmoothing(y, trend="add", damped_trend=True, seasonal="add",
                                 seasonal_periods=12, initialization_method="estimated").fit()
        return np.asarray(m.forecast(h))


def f_theta(y: np.ndarray, h: int, **_) -> np.ndarray:
    from statsmodels.tsa.forecasting.theta import ThetaModel
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # additive deseasonalisation keeps negative-valued variables (anomalies, LST in C) valid
        method = "multiplicative" if np.nanmin(y) > 0 else "additive"
        m = ThetaModel(y, period=12, deseasonalize=True, method=method).fit()
        return np.asarray(m.forecast(h))


MODELS = {"snaive": f_snaive, "harmonic_ar1": f_harmonic_ar1, "ets_damped": f_ets_damped, "theta": f_theta}


def _run(name: str, y: np.ndarray, h: int, t: np.ndarray, month0: np.ndarray) -> np.ndarray | None:
    t_f = t[-1] + np.arange(1, h + 1) / 12.0
    month0_f = (month0[-1] + np.arange(1, h + 1)) % 12
    try:
        out = MODELS[name](y, h, t=t, month0=month0, t_f=t_f, month0_f=month0_f)
        return out if np.all(np.isfinite(out)) else None
    except Exception:  # noqa: BLE001 - a failing model is simply excluded
        return None


def forecast_ensemble(time: pd.DatetimeIndex, y: np.ndarray, *, horizon: int = 60, folds: int = 4,
                      cv_horizon: int = 12, models: tuple[str, ...] = tuple(MODELS)) -> dict:
    y_obs = np.asarray(y, float)
    n = len(y_obs)
    if np.isfinite(y_obs).sum() < 48:
        return {"status": "too_short", "plain_language": "Need at least 4 years of data to project forward."}
    horizon = int(min(max(horizon, 1), 120))
    yf, n_filled = _fill_for_fit(time, y_obs)
    t = np.arange(n) / 12.0
    month0 = (time.month.to_numpy() - 1).astype(float)
    cv_h = int(min(cv_horizon, max(n // 8, 6)))
    folds = int(min(folds, max((n - 36) // cv_h, 1)))

    # seasonal-naive in-sample MAE as MASE scale
    d = np.abs(yf[12:] - yf[:-12])
    scale = float(np.mean(d)) if len(d) else 1.0
    scale = scale if scale > 0 else 1.0

    errors = {m: [] for m in models}
    fold_preds = {m: [] for m in models}
    actuals = []
    for k in range(folds, 0, -1):
        origin = n - k * cv_h
        if origin < 36:
            continue
        act = y_obs[origin:origin + cv_h]
        actuals.append(act)
        for m in models:
            p = _run(m, yf[:origin], cv_h, t[:origin], month0[:origin])
            fold_preds[m].append(p)
            if p is not None:
                errors[m].append(np.abs(act - p))
    mase = {}
    for m in models:
        if errors[m] and len(errors[m]) == len(actuals):
            e = np.concatenate(errors[m])
            mase[m] = float(np.nanmean(e) / scale)
    if not mase:
        return {"status": "failed", "plain_language": "No forecasting model could be fitted."}

    base = mase.get("snaive", np.inf)
    good = {m: v for m, v in mase.items() if m != "snaive" and v < base}
    if not good:
        good = {"snaive": base} if "snaive" in mase else dict(sorted(mase.items(), key=lambda kv: kv[1])[:1])
    w = {m: 1.0 / max(v, 1e-6) ** 2 for m, v in good.items()}
    tot = sum(w.values())
    weights = {m: v / tot for m, v in w.items()}

    # ensemble CV residuals -> conformal noise quantiles
    ens_err = []
    for fi, act in enumerate(actuals):
        preds = [fold_preds[m][fi] * weights[m] for m in weights if fold_preds[m][fi] is not None]
        if len(preds) == len(weights):
            ens_err.append(act - np.sum(preds, axis=0))
    ens_err = np.concatenate(ens_err) if ens_err else np.array([])
    ens_err = ens_err[np.isfinite(ens_err)]
    ens_mase = float(np.mean(np.abs(ens_err)) / scale) if len(ens_err) else None

    # final fit
    final = np.zeros(horizon)
    for m, wt in weights.items():
        p = _run(m, yf, horizon, t, month0)
        if p is None:
            continue
        final += wt * p
    t_f = t[-1] + np.arange(1, horizon + 1) / 12.0

    # trend-uncertainty cone from AR(1)-adjusted slope SE of the harmonic regression
    X = _design(t, month0)
    valid = np.isfinite(y_obs)
    beta, *_ = np.linalg.lstsq(X[valid], y_obs[valid], rcond=None)
    resid = np.full(n, np.nan)
    resid[valid] = y_obs[valid] - X[valid] @ beta
    r1 = max(lag1_autocorr(resid), 0.0)
    nv = int(valid.sum())
    neff = max(nv * (1 - r1) / (1 + r1), 8.0)
    s2 = float(np.nansum(resid ** 2) / (nv - X.shape[1]))
    cov = s2 * np.linalg.pinv(X[valid].T @ X[valid]) * (nv / neff)
    se_slope = float(math.sqrt(max(cov[1, 1], 0.0)))
    lead = t_f - t[valid][-1]

    bands = {}
    coverage = {}
    for level in (0.80, 0.95):
        if len(ens_err) >= 10:
            m_err = len(ens_err)
            q_level = min(1.0, math.ceil((m_err + 1) * level) / m_err)   # split-conformal quantile
            q = float(np.quantile(np.abs(ens_err), q_level))
            coverage[str(level)] = float(np.mean(np.abs(ens_err) <= q))
        else:
            q = float(stats.norm.ppf(0.5 + level / 2) * math.sqrt(s2))
        z = stats.norm.ppf(0.5 + level / 2)
        half = np.sqrt(q ** 2 + (z * se_slope * lead) ** 2)
        bands[str(level)] = (final - half, final + half)

    f_time = pd.date_range(time[-1] + pd.offsets.MonthBegin(1), periods=horizon, freq="MS")
    # year-average projection change (removes seasonality from the headline)
    last12 = np.nanmean(y_obs[-12:])
    end12 = float(np.mean(final[-12:]))
    skill = (1 - ens_mase / mase["snaive"]) if (ens_mase is not None and mase.get("snaive")) else None
    out = {
        "method": "CV-weighted ensemble (seasonal naive, harmonic+AR(1), damped Holt-Winters, Theta) "
                  "with split-conformal bands and trend-uncertainty cone",
        "disclaimer": "Statistical extrapolation of the observed record, not a physical climate projection.",
        "horizon_months": horizon,
        "cv": {"folds": len(actuals), "horizon": cv_h, "mase": mase, "ensemble_mase": ens_mase,
               "skill_vs_seasonal_naive": skill, "empirical_coverage": coverage},
        "weights": weights,
        "filled_for_fit": n_filled,
        "forecast": {
            "time": [d.strftime("%Y-%m-%d") for d in f_time],
            "mean": final.tolist(),
            "lo80": bands["0.8"][0].tolist(), "hi80": bands["0.8"][1].tolist(),
            "lo95": bands["0.95"][0].tolist(), "hi95": bands["0.95"][1].tolist(),
        },
        "last_12m_mean": float(last12),
        "projected_last_12m_mean": end12,
    }
    sk = f"{skill * 100:.0f}% better than" if skill is not None and skill > 0 else "no better than"
    out["plain_language"] = (
        f"If the recent behaviour continues, the 12-month average would move from {last12:.4g} to about "
        f"{end12:.4g} by {f_time[-1].year}. In back-tests this ensemble was {sk} simply repeating last year."
    )
    return out
