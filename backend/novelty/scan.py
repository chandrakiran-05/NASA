"""Trend Scan + Earth-System Coherence (research feature, see docs/07-novelty-research.md).

"Draw a box and we find which variables are trending — and whether their trends tell a
physically consistent story."

1. Analyse many variables for the same region and period.
2. Correct for testing many variables at once (Benjamini-Hochberg FDR).
3. Rank by Trend Evidence (significance + effect size in standard deviations per decade).
4. Coherence: for every pair of variables with a known physical link (catalog/data/links.json),
   check whether the trend signs agree with the expected relationship. The result is a
   "consistent / inconsistent / not testable" note, never a causal claim.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from statsmodels.stats.multitest import multipletests

LINKS = json.loads((Path(__file__).resolve().parents[1] / "catalog" / "data" / "links.json").read_text(encoding="utf-8"))["links"]


def rank_and_cohere(analyses: dict[str, dict], alpha: float = 0.05) -> dict:
    ids = list(analyses)
    p = np.array([max(analyses[i]["ols"]["p_adj"], analyses[i]["mann_kendall"]["p"]) for i in ids])
    rej, pf, _, _ = multipletests(p, alpha=alpha, method="fdr_bh") if len(ids) else ([], [], None, None)
    rows = []
    for k, vid in enumerate(ids):
        a = analyses[vid]
        resid_sd = np.nanstd(np.array(a["chart"]["deseasonalized"], dtype=float)) if a.get("chart") else None
        slope = a["sen"]["slope_per_decade"]
        effect = slope / resid_sd if resid_sd else None          # change per decade in standard deviations
        rows.append({"variable_id": vid, "label": a.get("label"), "units": a.get("units"),
                     "slope_per_decade": slope, "direction": a["verdict"]["direction"],
                     "p_raw": float(p[k]), "p_fdr": float(pf[k]), "significant_fdr": bool(rej[k]),
                     "effect_sd_per_decade": effect})
    rows.sort(key=lambda r: (not r["significant_fdr"], -(abs(r["effect_sd_per_decade"] or 0))))
    by = {r["variable_id"]: r for r in rows}
    coherence = []
    for ln in LINKS:
        if ln["a"] in by and ln["b"] in by:
            ra, rb = by[ln["a"]], by[ln["b"]]
            if not (ra["significant_fdr"] or rb["significant_fdr"]):
                status = "not_testable"
            else:
                agree = np.sign(ra["slope_per_decade"]) * np.sign(rb["slope_per_decade"]) == ln["expected_sign"]
                status = "consistent" if agree else "inconsistent"
            coherence.append({**ln, "status": status})
    n_sig = sum(r["significant_fdr"] for r in rows)
    incons = [c for c in coherence if c["status"] == "inconsistent"]
    txt = f"{n_sig} of {len(rows)} variables have a significant trend after correcting for testing them all."
    if coherence:
        txt += (f" {sum(c['status'] == 'consistent' for c in coherence)} physical links are consistent"
                + (f"; {len(incons)} are not — worth investigating (local drivers, data issues, or irrigation)."
                   if incons else "."))
    return {"ranking": rows, "coherence": coherence, "correction": "Benjamini-Hochberg FDR across variables",
            "plain_language": txt,
            "limit": "Coherence checks only the sign of trends against expected physics; it does not prove cause."}
