"""Regional contrast — "the same variable can trend one way here and the opposite way there".

Given analyses of the same variable over several regions:
  * Benjamini-Hochberg FDR correction across regions (Statsig guide: multiple comparisons)
  * pairwise slope-difference z-tests with AR(1)-adjusted standard errors
  * a divergence flag when two regions have significant trends of OPPOSITE sign.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats
from statsmodels.stats.multitest import multipletests


def compare_regions(results: list[dict], alpha: float = 0.05) -> dict:
    if len(results) < 2:
        raise ValueError("need at least two analysed series to compare")
    names = [r.get("label") or r.get("series_id") or f"region_{i}" for i, r in enumerate(results)]
    slopes = np.array([r["ols"]["slope_per_decade"] for r in results])
    se = np.array([r["ols"]["se_adj"] * 10 for r in results])
    p_ols = np.array([r["ols"]["p_adj"] for r in results])
    p_mk = np.array([r["mann_kendall"]["p"] for r in results])
    p_comb = np.maximum(p_ols, p_mk)            # conservative: both tests must agree
    rej, p_fdr, _, _ = multipletests(p_comb, alpha=alpha, method="fdr_bh")

    regions = []
    for i, r in enumerate(results):
        regions.append({
            "name": names[i], "series_id": r.get("series_id"),
            "slope_per_decade": float(slopes[i]), "sen_slope_per_decade": r["sen"]["slope_per_decade"],
            "p_raw": float(p_comb[i]), "p_fdr": float(p_fdr[i]), "significant_fdr": bool(rej[i]),
            "direction": "rising" if slopes[i] > 0 else "falling",
        })

    pairs = []
    for i, j in itertools.combinations(range(len(results)), 2):
        d = slopes[i] - slopes[j]
        s = math.hypot(se[i], se[j])
        z = d / s if s > 0 else 0.0
        p = float(2 * stats.norm.sf(abs(z)))
        opposite = bool(rej[i] and rej[j] and np.sign(slopes[i]) != np.sign(slopes[j]))
        pairs.append({"a": names[i], "b": names[j], "slope_diff_per_decade": float(d), "z": float(z),
                      "p_diff": p, "opposite_significant_trends": opposite})
    if pairs:
        _, pd_fdr, _, _ = multipletests([p["p_diff"] for p in pairs], alpha=alpha, method="fdr_bh")
        for p, q in zip(pairs, pd_fdr):
            p["p_diff_fdr"] = float(q)
            p["differ_significantly"] = bool(q < alpha)

    up = [r["name"] for r in regions if r["significant_fdr"] and r["direction"] == "rising"]
    down = [r["name"] for r in regions if r["significant_fdr"] and r["direction"] == "falling"]
    divergent = any(p["opposite_significant_trends"] for p in pairs)
    if divergent:
        txt = (f"Opposite trends: significantly rising in {', '.join(up)} but falling in {', '.join(down)} "
               "(after correcting for testing several regions). The same driver can produce opposite "
               "regional responses, so this is a good place to look for the underlying process.")
    elif up or down:
        txt = (f"Significant trends (FDR-corrected) in: {', '.join(up + down)}. "
               "No region shows a significant trend in the opposite direction.")
    else:
        txt = "No region has a significant trend once the multiple-testing correction is applied."
    return {"alpha": alpha, "correction": "Benjamini-Hochberg FDR", "regions": regions, "pairs": pairs,
            "divergent": divergent, "plain_language": txt}
