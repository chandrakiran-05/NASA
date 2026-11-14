"""Engineer tools on top of the twin engine: compound thresholds, named scenario sets, knob sensitivity.
Everything is a simulation from the uploaded data (label "simulated"); nothing here is a prediction."""
from __future__ import annotations


import numpy as np
import pandas as pd

from ..core.errors import InvalidRequest
from ..timeseries.model import MonthlySeries
from .engine import DISCLAIMER, simulate

MAX_KNOBS = 10
INTERACTION_NOTE = ("Knobs interact (drivers pass changes between variables), so these one-at-a-time effects do "
                    "not add up to the total. Association in the simulation is not cause in the real system.")


def _run_matrix(series, scenario, horizon_years, n_runs, seed):
    res = simulate(series, scenario, horizon_years=horizon_years, n_runs=n_runs, seed=seed, return_runs=True)
    return {name: (v.pop("_runs"), pd.DatetimeIndex(pd.to_datetime(v["time"]))) for name, v in res["variables"].items()}


def compound(series, scenario: dict, conditions: list[dict], *, horizon_years=30, n_runs=500, seed=2026) -> dict:
    """Share of runs in which every condition is met in the same calendar year (any month of that year)."""
    unknown = ({c["variable"] for c in conditions} | set(scenario)) - set(series)
    if unknown:
        raise InvalidRequest(f"Names variables not in this twin: {sorted(unknown)}")
    mats = _run_matrix(series, scenario, horizon_years, n_runs, seed)
    years = None
    per_cond = []
    for c in conditions:
        vals, t = mats[c["variable"]]
        hit = vals >= c["value"] if c.get("direction", "above") == "above" else vals <= c["value"]
        yrs = t.year.to_numpy()
        ys = sorted(set(yrs))
        per_year = np.stack([hit[:, yrs == Y].any(axis=1) for Y in ys], axis=1)   # runs x years
        per_cond.append(dict(zip(ys, per_year.T)))
        years = set(ys) if years is None else years & set(ys)
    years = sorted(years)
    together = np.stack([np.logical_and.reduce([pc[Y] for pc in per_cond]) for Y in years], axis=1)
    ever = together.any(axis=1)
    singles = [{**c, "probability_by_end": float(np.stack([pc[Y] for Y in years], 1).any(1).mean())}
               for c, pc in zip(conditions, per_cond)]
    names = " and ".join(f"{c['variable']} {'≥' if c.get('direction', 'above') == 'above' else '≤'} {c['value']}"
                         for c in conditions)
    return {"horizon_years": horizon_years, "n_runs": n_runs, "seed": seed, "conditions": singles,
            "probability_same_year": [{"year": int(Y), "p": float(together[:, i].mean())} for i, Y in enumerate(years)],
            "probability_by_end": float(ever.mean()),
            "plain_language": f"In {ever.mean():.0%} of {n_runs} simulated runs, {names} happen in the same year "
                              f"at least once by {years[-1] if years else '-'}.",
            "label": "simulated", "disclaimer": DISCLAIMER}


def scenario_set(series, scenarios: dict[str, dict], **kw) -> dict:
    """Several named scenarios, same seed: differences come only from the knobs."""
    out = {}
    for label, sc in scenarios.items():
        r = simulate(series, sc, **kw)
        out[label] = {name: {"time": v["time"], "p50": v["p50"], "threshold": v.get("threshold"), "label": "simulated"}
                      for name, v in r["variables"].items()}
    return {**{k: kw[k] for k in ("horizon_years", "n_runs", "seed")}, "scenarios": out, "label": "simulated",
            "disclaimer": DISCLAIMER}


def _knobs(scenario: dict) -> list[tuple[str, str, int | None]]:
    """Each trend setting is one knob; each shock and each driver is its own knob."""
    return [(v, k, i) for v, sc in scenario.items() for k, x in sc.items() if k != "threshold"
            for i in (range(len(x)) if isinstance(x, list) else [None])]


def _without(scenario: dict, knob) -> dict:
    v, k, i = knob
    sc = {n: dict(s) for n, s in scenario.items()}
    if i is None:
        del sc[v][k]
    else:
        sc[v][k] = [x for j, x in enumerate(sc[v][k]) if j != i]
    return sc


def sensitivity(series, scenario: dict, target: str, **kw) -> dict:
    """Remove one knob at a time (same seed) and rank by how much the target's crossing probability moves."""
    if not (scenario.get(target) or {}).get("threshold"):
        raise InvalidRequest(f"Give {target!r} a threshold in the scenario")
    knobs = _knobs(scenario)
    if len(knobs) > MAX_KNOBS:
        raise InvalidRequest(f"At most {MAX_KNOBS} knobs for sensitivity; got {len(knobs)}")
    p = lambda sc: simulate(series, sc, **kw)["variables"][target]["threshold"]["probability_by_end"]
    full = p(scenario)
    rows = []
    for knob in knobs:
        v, k, i = knob
        without = p(_without(scenario, knob))
        rows.append({"variable": v, "knob": k, "item": i, "setting": scenario[v][k] if i is None else scenario[v][k][i],
                     "probability_without": without, "change": full - without})
    rows.sort(key=lambda r: -abs(r["change"]))
    return {**{k: kw[k] for k in ("horizon_years", "n_runs", "seed")}, "target": target,
            "probability_with_all_knobs": full, "ranking": rows, "note": INTERACTION_NOTE, "label": "simulated",
            "disclaimer": DISCLAIMER}
