"""F1 — Seam & Integrity Audit (team signature feature, docs/06-feature-spec.md).

"Before we call it a trend, we check it isn't a broken record or a satellite swap."

* integrity flags  : runs of exact zeros / constant values, low-coverage months, data retrieved
                     before a NASA pipeline fix (the 2026-03-26 Cloud Giovanni zero-block alert)
* seam markers     : cited instrument / observing-system / orbit events (catalog/data/events.json)
* step tests       : OLS with linear trend + step dummy at each seam, AR(1)-adjusted p-value,
                     trend before vs after
* Pettitt test     : unknown single break (Pettitt 1979), O(n log n) via ranks
* trend-or-jump    : BIC comparison of "trend", "one jump" and "trend + jump" models
* badge            : OK / CAUTION / NOT_FIT with reasons. Wording is always "possible instrument
                     effect", never "artifact": a step can be a real climate shift.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ..analysis.trend import effective_n, lag1_autocorr
from ..timeseries.model import MonthlySeries

EVENTS = json.loads((Path(__file__).resolve().parents[1] / "catalog" / "data" / "events.json").read_text())["events"]


# ------------------------------------------------------------------ integrity flags
def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        if not m and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def zero_and_constant_runs(ms: MonthlySeries, min_len: int = 3) -> list[dict]:
    v = ms.value
    flags = []
    zero = np.isfinite(v) & (v == 0.0)
    for a, b in runs(zero):
        if b - a + 1 >= min_len:
            flags.append({"type": "zero_run", "start": ms.time[a].strftime("%Y-%m"), "end": ms.time[b].strftime("%Y-%m"),
                          "months": b - a + 1, "message": f"{b - a + 1} consecutive months of exactly 0"})
    same = np.zeros(len(v), bool)
    same[1:] = np.isfinite(v[1:]) & (v[1:] == v[:-1]) & (v[1:] != 0)
    for a, b in runs(same):
        n = b - a + 2
        if n >= min_len:
            flags.append({"type": "constant_run", "start": ms.time[a - 1].strftime("%Y-%m"),
                          "end": ms.time[b].strftime("%Y-%m"), "months": n,
                          "message": f"{n} consecutive months with an identical value"})
    return flags


def coverage(ms: MonthlySeries, low: float = 0.7) -> dict:
    ratio = ms.qc_pass_ratio if ms.qc_pass_ratio is not None else np.isfinite(ms.value).astype(float)
    ratio = np.clip(np.nan_to_num(np.asarray(ratio, float), nan=0.0), 0, 1)
    low_m = ratio < low
    return {"time": [t.strftime("%Y-%m") for t in ms.time], "fraction_valid": [round(float(x), 3) for x in ratio],
            "low_coverage_months": int(low_m.sum()), "low_coverage_pct": round(100 * float(low_m.mean()), 1),
            "threshold": low}


def pipeline_fix_flags(ms: MonthlySeries) -> list[dict]:
    p = ms.provenance
    ds = (p.dataset_short_name or "") + " " + (p.variable or "")
    out = []
    for ev in EVENTS:
        fix = ev.get("retrieval_fix_date")
        if not fix or not any(ds.startswith(a) or a in ds for a in ev["applies_to"]):
            continue
        before = ev.get("affects_data_before")
        if before and ms.time[0] >= pd.Timestamp(before):
            continue
        if p.retrieved_at and p.retrieved_at[:10] < fix:
            out.append({"type": "retrieved_before_fix", "event": ev["id"], "message":
                        f"Data retrieved on {p.retrieved_at[:10]}, before NASA's fix on {fix}. Re-fetch it.",
                        "url": ev["url"]})
    return out


def days_in_month_note(units: str | None) -> str | None:
    if units and "month" in units.lower() and "/" in units:
        return ("Units are per month: longer months hold more. Convert to a daily rate before comparing "
                "months (Giovanni user guide).")
    return None


# ------------------------------------------------------------------ seams and breaks
def events_for(ms: MonthlySeries) -> list[dict]:
    p = ms.provenance
    keys = [p.dataset_short_name or "", p.product_id or "", p.variable or ""]
    t0, t1 = ms.time[0], ms.time[-1]
    out = []
    for ev in EVENTS:
        if ev.get("type") == "data_pipeline_fix":
            continue
        if not any(k and (k.startswith(a) or a in k) for a in ev["applies_to"] for k in keys):
            continue
        d = pd.Timestamp(ev["date"] + "-01")
        if t0 < d <= t1:
            out.append(ev)
    return out


def _fit(X: np.ndarray, y: np.ndarray):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return beta, resid, float(resid @ resid)


def step_test(t: np.ndarray, y: np.ndarray, time: pd.DatetimeIndex, date: str, min_side: int = 24) -> dict:
    """Trend + step-dummy OLS at a known date; AR(1)-adjusted p for the step; per-side trends."""
    m = np.isfinite(y)
    d = pd.Timestamp(date + "-01")
    after = np.asarray(time >= d)
    nb, na = int((m & ~after).sum()), int((m & after).sum())
    if nb < min_side or na < min_side:
        return {"date": date, "status": "too_short", "n_before": nb, "n_after": na}
    tt, yy, aa = t[m], y[m], after[m].astype(float)
    X = np.column_stack([np.ones_like(tt), tt, aa])
    beta, resid, rss = _fit(X, yy)
    n, k = len(yy), 3
    r1 = lag1_autocorr(resid)
    neff = effective_n(n, r1)
    s2 = rss / (n - k)
    cov = s2 * np.linalg.inv(X.T @ X) * (n - k) / max(neff - k, 1.0)
    se = math.sqrt(max(cov[2, 2], 0))
    tstat = beta[2] / se if se > 0 else 0.0
    p = float(2 * stats.t.sf(abs(tstat), max(neff - k, 1.0)))

    def side(mask):
        xs, ys = tt[mask], yy[mask]
        b = np.polyfit(xs, ys, 1)[0]
        return float(b * 10)

    return {"date": date, "status": "ok", "step": float(beta[2]), "step_p": p,
            "trend_before_per_decade": side(aa == 0), "trend_after_per_decade": side(aa == 1),
            "n_before": nb, "n_after": na, "significant": p < 0.05}


def pettitt(y: np.ndarray) -> dict:
    """Pettitt (1979) single change-point test on the valid values, O(n log n) via ranks."""
    v = y[np.isfinite(y)]
    n = len(v)
    if n < 10:
        return {"status": "too_short"}
    r = stats.rankdata(v)
    k = np.arange(1, n)
    U = 2 * np.cumsum(r)[:-1] - k * (n + 1)
    i = int(np.argmax(np.abs(U)))
    K = float(abs(U[i]))
    p = float(min(1.0, 2 * math.exp(-6 * K ** 2 / (n ** 3 + n ** 2))))
    return {"status": "ok", "index_valid": i + 1, "K": K, "p": p}


def trend_or_jump(t: np.ndarray, y: np.ndarray, time: pd.DatetimeIndex) -> dict:
    """Is the change a steady trend, a single jump, or both? BIC with an AR(1) effective sample size."""
    m = np.isfinite(y)
    tt, yy = t[m], y[m]
    tv = time[m]
    pt = pettitt(y)
    if pt.get("status") != "ok":
        return {"status": "too_short"}
    j = pt["index_valid"]
    step = (np.arange(len(yy)) >= j).astype(float)
    models = {
        "trend": np.column_stack([np.ones_like(tt), tt]),
        "jump": np.column_stack([np.ones_like(tt), step]),
        "trend_plus_jump": np.column_stack([np.ones_like(tt), tt, step]),
    }
    _, r_tr, _ = _fit(models["trend"], yy)
    neff = effective_n(len(yy), lag1_autocorr(r_tr))
    bic = {}
    for name, X in models.items():
        _, _, rss = _fit(X, yy)
        bic[name] = neff * math.log(max(rss, 1e-300) / len(yy)) + X.shape[1] * math.log(neff)
    best = min(bic, key=bic.get)
    date = tv[j].strftime("%Y-%m")
    txt = {"trend": "a steady trend explains the data best",
           "jump": f"a single jump around {date} explains the data better than a steady trend",
           "trend_plus_jump": f"there is both a trend and a jump around {date}"}[best]
    return {"status": "ok", "pettitt_date": date, "pettitt_p": pt["p"], "bic": bic, "best_model": best,
            "plain_language": txt[0].upper() + txt[1:] + "."}


# ------------------------------------------------------------------ audit
def integrity_audit(ms: MonthlySeries, deseasonalized: np.ndarray) -> dict:
    t = ms.t_years()
    reasons, level = [], 0          # 0 OK, 1 CAUTION, 2 NOT_FIT
    comp = ms.completeness()
    flags = zero_and_constant_runs(ms) + pipeline_fix_flags(ms)
    cov = coverage(ms)
    if comp["n_valid"] < 24 or comp["missing_pct"] > 50:
        level = 2
        reasons.append(f"Only {comp['n_valid']} valid months ({comp['missing_pct']}% missing).")
    for f in flags:
        if f["type"] == "zero_run" and f["months"] >= 6:
            level = max(level, 2)
            reasons.append(f"Suspicious block of zeros {f['start']}–{f['end']} (cf. NASA's Cloud Giovanni zero-block bug).")
        elif f["type"] == "retrieved_before_fix":
            level = max(level, 2)
            reasons.append(f["message"])
        else:
            level = max(level, 1)
            reasons.append(f["message"] + f" ({f['start']}–{f['end']}).")
    if cov["low_coverage_pct"] > 10:
        level = max(level, 1)
        reasons.append(f"{cov['low_coverage_pct']}% of months have low coverage.")
    seams = []
    for ev in events_for(ms):
        st = step_test(t, deseasonalized, ms.time, ev["date"])
        st.update({"event": ev["id"], "type": ev["type"], "description": ev["description"],
                   "citation": ev["citation"], "url": ev["url"], "verify_citation": ev.get("verify", False)})
        seams.append(st)
        if st.get("significant"):
            level = max(level, 1)
            reasons.append(f"Possible instrument effect at {ev['date']} ({ev['id']}): the level shifts by "
                           f"{st['step']:+.3g} {ms.units or ''} (p = {st['step_p']:.3f}).")
    toj = trend_or_jump(t, deseasonalized, ms.time)
    if toj.get("best_model") == "jump" and toj.get("pettitt_p", 1) < 0.05:
        level = max(level, 1)
        reasons.append(toj["plain_language"])
    note = days_in_month_note(ms.units)
    if note:
        level = max(level, 1)
        reasons.append(note)
    badge = ["OK", "CAUTION", "NOT_FIT"][level]
    if not reasons:
        reasons.append("No integrity problems, instrument seams or jumps detected.")
    return {"badge": badge, "badge_icon": ["✅", "⚠️", "❌"][level], "reasons": reasons, "flags": flags,
            "coverage": cov, "seams": seams, "trend_or_jump": toj,
            "limits": ["A step can be a real climate shift, not only an instrument effect.",
                       "The event list is incomplete.", "Short segments have low statistical power."]}
