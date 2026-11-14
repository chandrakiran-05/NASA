"""F4 — Second Opinion: does another NASA product (or the nearest station) agree on the trend?

* same units  -> trend test on the DIFFERENCE series (A - B) on common months; if the difference
                 has its own significant trend, the products disagree about the rate
* other units -> compare trend signs and significance only (e.g. land-surface vs air temperature)
Badge: ROBUST (same sign and same significance, difference not significant), DISPUTED (opposite
significant signs, or a significant trend in the difference), INCONCLUSIVE otherwise.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from ..analysis.deseason import deseasonalize
from ..analysis.trend import mann_kendall, ols_trend
from ..timeseries.model import MonthlySeries, Provenance

GROUPS = json.loads((Path(__file__).resolve().parents[1] / "catalog" / "data" / "quantity_groups.json").read_text(encoding="utf-8"))["groups"]


def second_opinions(variable_id: str) -> dict:
    for g in GROUPS:
        if variable_id in g["members"] or variable_id in g.get("sign_only", []):
            same = [m for m in g["members"] if m != variable_id] if variable_id in g["members"] else []
            sign = [m for m in g["members"] + g.get("sign_only", []) if m != variable_id and m not in same]
            return {"group": g["id"], "name": g["name"], "same_quantity": same, "sign_only": sign,
                    "systems": g.get("system", {})}
    return {"group": None, "same_quantity": [], "sign_only": []}


def _summ(ms: MonthlySeries, alpha: float) -> dict:
    t = ms.t_years()
    y = deseasonalize(ms, "stl").deseasonalized
    o = ols_trend(t, y, alpha)
    mk = mann_kendall(t, y, alpha, "ess_ar1")
    return {"label": ms.label, "units": ms.units, "source": ms.provenance.source_api,
            "slope_per_decade": o.slope * 10, "se_adj_per_decade": o.se_adj * 10, "p_adj": o.p_adj, "mk_p": mk.p,
            "significant": o.p_adj < alpha and mk.p < alpha}


def product_agreement(a: MonthlySeries, b: MonthlySeries, alpha: float = 0.05) -> dict:
    sa, sb = _summ(a, alpha), _summ(b, alpha)
    same_units = (a.units or "").strip().lower() == (b.units or "").strip().lower()
    out = {"a": sa, "b": sb, "same_units": same_units}
    diff_sig = False
    if same_units:
        s1 = pd.Series(a.value, index=a.time)
        s2 = pd.Series(b.value, index=b.time)
        d = (s1 - s2).dropna()
        if len(d) >= 36:
            idx = pd.date_range(d.index.min(), d.index.max(), freq="MS")
            dm = MonthlySeries(idx, d.reindex(idx).to_numpy(), a.units, Provenance("derived", "difference", {}),
                               label=f"{a.label} minus {b.label}")
            sd = _summ(dm, alpha)
            diff_sig = sd["significant"]
            out["difference"] = {**sd, "n_common_months": int(len(d)),
                                 "mean_offset": float(d.mean())}
        z = (sa["slope_per_decade"] - sb["slope_per_decade"]) / math.hypot(sa["se_adj_per_decade"], sb["se_adj_per_decade"])
        out["slope_difference"] = {"z": z, "p": float(2 * stats.norm.sf(abs(z)))}
    same_sign = np.sign(sa["slope_per_decade"]) == np.sign(sb["slope_per_decade"])
    if (not same_sign and (sa["significant"] or sb["significant"])) or diff_sig:
        badge = "DISPUTED"
        txt = ("The two sources disagree: " + ("their trends point in opposite directions" if not same_sign
                                                else "the gap between them is itself trending") + ".")
    elif same_sign and sa["significant"] == sb["significant"]:
        badge = "ROBUST"
        txt = ("Both sources agree: " + ("a significant " + ("rise" if sa["slope_per_decade"] > 0 else "fall")
                                          if sa["significant"] else "no significant trend") + ".")
    else:
        badge = "INCONCLUSIVE"
        txt = "The sources point the same way but only one finds the trend significant."
    out.update({"badge": badge, "plain_language": txt,
                "limits": ["A single station does not fully represent a grid cell.",
                           "When units differ only the sign of the trend is compared."]})
    return out
