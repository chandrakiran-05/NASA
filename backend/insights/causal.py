"""WHY is it changing? Suspect testing with PCMCI+ (Trend Forensics, docs/07).

PCMCI+ (Runge 2020, UAI; Runge et al. 2019, Sci. Adv. 5:eaau4996) tests lagged links
"X at lag tau -> Y" with conditional-independence tests. Unlike pairwise lagged correlation it
conditions on the *pasts of both variables and of the other candidates*, so it removes links
that are only due to persistence or to a common driver (McGraw & Barnes 2018, J. Climate).

Input preparation (Krich et al. 2020, Biogeosciences: non-stationarity creates false links):
seasonal climatology removed, linear trend removed, months aligned on the common record.
Missing months are flagged (tigramite `missing_flag`), never filled.

Every link gets: lag, partial correlation (effect), p-value with Benjamini-Hochberg FDR across
all tested links, and a half-record robustness check (link must keep its sign and stay
significant at p<0.1 in both halves). Wording is always "consistent with ... (association)".

Pre-registered suspects
-----------------------
`judge_suspects` takes hypotheses made BEFORE seeing data (textbook bundle and/or the local AI,
restricted to catalog ids) and stamps each one:
    supported      significant link driver -> target with the expected sign
    opposite_sign  significant link but with the opposite sign
    not_supported  no significant link at lags 0..tau_max
Links the data show but nobody predicted are listed as `unexpected`.

If tigramite is not installed, the module falls back to detrended lagged correlation with
Bretherton n_eff (backend/insights/drivers.py) and says so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from ..timeseries.model import MonthlySeries
from .drivers import _detrended_anoms, driver_analysis

try:  # optional, GPL-3.0: pip install tigramite
    from tigramite import data_processing as _pp
    from tigramite.independence_tests.parcorr import ParCorr as _ParCorr
    from tigramite.pcmci import PCMCI as _PCMCI
except ImportError:  # pragma: no cover
    _PCMCI = None

CITATIONS = [
    {"text": "Runge J. et al. 2019, Detecting and quantifying causal associations in large nonlinear time series "
             "datasets. Sci. Adv. 5:eaau4996", "doi": "10.1126/sciadv.aau4996"},
    {"text": "Runge J. 2020, Discovering contemporaneous and lagged causal relations in autocorrelated "
             "nonlinear time series datasets (PCMCI+). UAI 2020", "url": "https://arxiv.org/abs/2003.03685"},
    {"text": "Krich C. et al. 2020, Estimating causal networks in biosphere-atmosphere interaction with the "
             "PCMCI approach. Biogeosciences 17:1033", "doi": "10.5194/bg-17-1033-2020"},
]
MISSING = 999999.0
MIN_OVERLAP = 60


def available() -> bool:
    return _PCMCI is not None


def _frame(target: MonthlySeries, drivers: list[MonthlySeries]) -> tuple[pd.DataFrame, list[str]]:
    cols = {"target": _detrended_anoms(target)[0]}
    names = ["target"]
    for i, d in enumerate(drivers):
        key = d.variable_id or d.label or f"driver_{i}"
        while key in cols:
            key += "_"
        cols[key] = _detrended_anoms(d)[0]
        names.append(key)
    df = pd.concat(cols, axis=1, join="outer").sort_index()
    df = df.loc[df.notna().all(axis=1).idxmax():]          # start where every series has begun
    last = df.notna().all(axis=1)[::-1].idxmax()
    df = df.loc[:last]
    return df, names


def _pcmci(df: pd.DataFrame, tau_max: int, pc_alpha: float | None):
    X = df.to_numpy(dtype=float)
    mask = ~np.isfinite(X)
    X = np.where(mask, MISSING, X)
    data = _pp.DataFrame(X, var_names=list(df.columns), missing_flag=MISSING)
    pc = _PCMCI(dataframe=data, cond_ind_test=_ParCorr(significance="analytic"), verbosity=0)
    res = pc.run_pcmciplus(tau_min=0, tau_max=tau_max, pc_alpha=pc_alpha)
    return res


def _links_into_target(res: dict, names: list[str], tau_max: int) -> list[dict]:
    p, v = res["p_matrix"], res["val_matrix"]
    rows = []
    for i, nm in enumerate(names):
        if nm == "target":
            continue
        for tau in range(0, tau_max + 1):
            rows.append({"driver": nm, "lag_months": tau, "partial_r": float(v[i, 0, tau]), "p": float(p[i, 0, tau]),
                         "graph": str(res["graph"][i, 0, tau])})
    return rows


def causal_screen(target: MonthlySeries, drivers: list[MonthlySeries], *, tau_max: int = 3, alpha: float = 0.05,
                  pc_alpha: float | None = 0.2) -> dict:
    if not available():
        fb = driver_analysis(target, drivers, max_lag=tau_max, alpha=alpha)
        fb["method"] = "fallback: " + fb["method"] + " (tigramite not installed)"
        return {"status": "fallback", **fb}
    df, names = _frame(target, drivers)
    n_rows = int(df.notna().all(axis=1).sum())
    if n_rows < MIN_OVERLAP:
        return {"status": "insufficient_overlap", "n_months_common": n_rows, "links": [],
                "plain_language": f"The series overlap for only {n_rows} complete months; at least {MIN_OVERLAP} "
                                  f"are needed to test drivers."}
    res = _pcmci(df, tau_max, pc_alpha)
    links = _links_into_target(res, names, tau_max)
    rej, q, _, _ = multipletests([lk["p"] for lk in links], alpha=alpha, method="fdr_bh")
    for lk, qq, rr in zip(links, q, rej):
        lk["p_fdr"] = float(qq)
        lk["significant"] = bool(rr)

    # half-record robustness for significant links
    sig = [lk for lk in links if lk["significant"]]
    if sig:
        mid = len(df) // 2
        halves = []
        for part in (df.iloc[:mid], df.iloc[mid:]):
            try:
                halves.append(_links_into_target(_pcmci(part, tau_max, pc_alpha), names, tau_max)
                              if int(part.notna().all(axis=1).sum()) >= 36 else None)
            except Exception:  # noqa: BLE001 - robustness check must not break the main result
                halves.append(None)
        for lk in sig:
            ok = []
            for h in halves:
                if h is None:
                    ok.append(None)
                    continue
                m = next(x for x in h if x["driver"] == lk["driver"] and x["lag_months"] == lk["lag_months"])
                ok.append(bool(m["p"] < 0.1 and np.sign(m["partial_r"]) == np.sign(lk["partial_r"])))
            lk["robust_both_halves"] = None if None in ok else all(ok)

    best = {}
    for lk in links:
        b = best.get(lk["driver"])
        if b is None or (lk["significant"], -lk["p_fdr"]) > (b["significant"], -b["p_fdr"]):
            best[lk["driver"]] = lk
    return {
        "status": "ok",
        "method": "PCMCI+ (ParCorr), detrended seasonal anomalies, BH-FDR over all links, half-record robustness",
        "citations": CITATIONS,
        "n_months_common": n_rows,
        "period": [df.index[0].strftime("%Y-%m"), df.index[-1].strftime("%Y-%m")],
        "tau_max": tau_max,
        "links": links,
        "best_per_driver": list(best.values()),
        "disclaimer": "PCMCI+ finds statistically supported lagged dependencies, consistent with a driver; it assumes "
                      "no unobserved common drivers and linear relations. It is association evidence, not proof.",
        "explains": "month-to-month anomalies (seasons and linear trends removed), not the long-term trend itself",
    }


def judge_suspects(screen: dict, suspects: list[dict]) -> dict:
    """Stamp pre-registered suspects with what the data say."""
    if screen.get("status") not in ("ok",):
        return {"suspects": [dict(s, status="untested") for s in suspects], "unexpected": [],
                "plain_language": screen.get("plain_language") or "Driver test could not run.",
                "screen_status": screen.get("status")}
    best = {b["driver"]: b for b in screen["best_per_driver"]}
    out = []
    for s in suspects:
        b = best.get(s["driver_id"])
        row = dict(s)
        if b is None:
            row.update(status="untested", reason="driver series not available")
        elif not b["significant"]:
            row.update(status="not_supported", lag_months_found=None, partial_r=b["partial_r"], p_fdr=b["p_fdr"])
        else:
            exp = s.get("expected_sign", "either")
            sign = "+" if b["partial_r"] > 0 else "-"
            robust = b.get("robust_both_halves")
            if robust is False:
                st = "unstable"          # significant overall but not in both halves: do not count it
            else:
                st = "supported" if exp in ("either", sign) else "opposite_sign"
            row.update(status=st, lag_months_found=b["lag_months"], partial_r=b["partial_r"], p_fdr=b["p_fdr"],
                       robust_both_halves=robust)
        out.append(row)
    sup = [r for r in out if r["status"] == "supported"]
    sup_names = [r.get("driver_name", r["driver_id"]) for r in sup]
    for r in out:
        if r["status"] in ("not_supported", "unstable") and sup_names:
            r["note"] = ("no direct link once the other variables are accounted for; it may act through "
                         + ", ".join(sup_names))
    named = {s["driver_id"] for s in suspects}
    unexpected = [b for b in screen["best_per_driver"] if b["significant"] and b["driver"] not in named
                  and b.get("robust_both_halves") is not False]
    parts = []
    for r in sup:
        lag = "in the same month" if r["lag_months_found"] == 0 else f"{r['lag_months_found']} month(s) later"
        parts.append(f"{r.get('driver_name', r['driver_id'])}: the target responds {lag} "
                     f"(partial r = {r['partial_r']:.2f}), consistent with the hypothesis")
    txt = ("; ".join(parts) + ". ") if parts else "None of the suspects is supported by the data. "
    rejected = [r.get("driver_name", r["driver_id"]) for r in out if r["status"] in ("not_supported", "opposite_sign")]
    unstable = [r.get("driver_name", r["driver_id"]) for r in out if r["status"] == "unstable"]
    if rejected:
        txt += "Not supported as a direct link: " + ", ".join(rejected) + ". "
    if unstable:
        txt += "Unstable (not seen in both halves of the record): " + ", ".join(unstable) + ". "
    txt += "These are statistical associations after removing seasons, trends and persistence, not proof of cause."
    return {"suspects": out, "unexpected": unexpected, "plain_language": txt, "screen_status": "ok"}
