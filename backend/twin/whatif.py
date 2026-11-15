"""What-if questions for DigiTwin, answered for every place named in the question.

"If global temperature rises 5 °C, how does the trend change in Chennai and California?"
  1. the planner reads the places and the variable;
  2. the change is parsed from the words (+5 °C, +20 %, doubled, halved, by 2050...);
  3. each place's real monthly record is fetched (NASA first, keyless NOAA fallback);
  4. the twin engine simulates the record forward twice, with and without the change (same random noise);
  5. per place: observed annual means, both simulated bands, the trend with and without the change.
Everything here is simulated from a fitted baseline: "simulated", never a prediction.
"""
from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd

from ..core.errors import InvalidRequest
from .engine import DISCLAIMER, baseline, simulate

DEFAULT_TARGET_YEAR = 2100
BASE_YEARS = 30            # record used to fit each place's baseline
N_RUNS = 400

_NUM = r"(\d+(?:\.\d+)?)"
_DOWN = re.compile(r"\b(fall|falls|drop|drops|decreas\w*|cool\w*|lower\w*|declin\w*|reduc\w*|less|shrink\w*|minus)\b")
_MULT = {"doubl": 2.0, "twice": 2.0, "tripl": 3.0, "thrice": 3.0, "halv": 0.5, "half": 0.5}


def parse_change(question: str) -> dict | None:
    """The change the question asks about, or None. Returns {kind: add|pct|multiply|shock, value, unit,
    target_year, scope, text}. Years (19xx/20xx) are never read as the size of the change."""
    q = question.lower().replace("°", " ° ").replace("º", " ° ")
    m = re.search(r"\bby\s+((?:19|20|21)\d\d)\b|\bin\s+((?:20|21)\d\d)\b|\buntil\s+((?:20|21)\d\d)\b", q)
    target = int(next(g for g in m.groups() if g)) if m else None
    scope = "global" if re.search(r"\b(global\w*|world\w*|planet\w*|earth)\b", q) else "local"
    for k, f in _MULT.items():
        if re.search(rf"\b{k}\w*", q):
            return {"kind": "multiply", "value": f, "unit": None, "target_year": target, "scope": scope,
                    "text": f"trend x{f:g}"}
    m = re.search(rf"(\d+(?:\.\d+)?)\s*(?:x|times)\b", q)
    if m:
        return {"kind": "multiply", "value": float(m.group(1)), "unit": None, "target_year": target,
                "scope": scope, "text": f"trend x{float(m.group(1)):g}"}
    sign = -1.0 if _DOWN.search(q) else 1.0
    for m in re.finditer(rf"([+-])?\s*{_NUM}\s*(%|percent|per ?cent|°\s*c|° ?f|°|deg\w*\s*(?:c|f|celsius|fahrenheit)?|celsius|fahrenheit|c\b|f\b|k\b|kelvin|mm\w*)?", q):
        num, unit = float(m.group(2)), (m.group(3) or "").replace(" ", "")
        if re.fullmatch(r"(19|20|21)\d\d", m.group(2)) and not unit:
            continue                                   # a year, not the size of the change
        if not unit and not m.group(1):
            continue                                   # a bare number without unit or sign is ambiguous
        s = -1.0 if m.group(1) == "-" else (1.0 if m.group(1) == "+" else sign)
        kind = "pct" if unit.startswith(("%", "percent", "per")) else "add"
        if unit.endswith(("f", "fahrenheit")) and kind == "add":
            num, unit = num * 5 / 9, "°C"             # a temperature difference in °F, as °C
        elif unit.startswith(("°", "deg", "c", "celsius", "k", "kelvin")):
            unit = "°C"
        shock = bool(re.search(r"\b(sudden\w*|jump\w*|shock|step|overnight|at once)\b", q))
        return {"kind": "shock" if shock and kind == "add" else kind, "value": s * num,
                "unit": unit or None, "target_year": target, "scope": scope,
                "text": f"{s * num:+.3g}{'%' if kind == 'pct' else (' ' + unit if unit else '')}"}
    return None


def knobs_for(change: dict, ms, horizon_years: int, start_year: int) -> tuple[dict, str]:
    """Twin knobs that add exactly the asked change by the target year (a steady ramp), plus a plain sentence."""
    if change["kind"] == "multiply":
        return ({"trend_multiplier": change["value"]},
                f"the place's own fitted trend multiplied by {change['value']:g}")
    size = change["value"]
    if change["kind"] == "pct":
        mean = float(np.nanmean(ms.value))
        size = mean * change["value"] / 100
        what = f"{change['value']:+g}% of its average ({size:+.3g} {ms.units or ''})".strip()
    else:
        what = f"{size:+g} {ms.units or change['unit'] or ''}".strip()
    if change["kind"] == "shock":
        return ({"shocks": [{"year": start_year + 1, "size": size}]}, f"a sudden step of {what} from {start_year + 1}")
    return ({"trend_add_per_decade": size / (horizon_years / 10)},
            f"{what} added as a steady extra trend, reached by {start_year + horizon_years}")


def _annual(runs: np.ndarray, time: pd.DatetimeIndex) -> tuple[list[int], np.ndarray]:
    years = sorted(set(time.year))
    full = [y for y in years if (time.year == y).sum() == 12]
    means = np.stack([runs[:, time.year == y].mean(axis=1) for y in full], axis=1)
    return full, means


def _band(means: np.ndarray) -> dict:
    p05, p50, p95 = np.percentile(means, [5, 50, 95], axis=0)
    return {"p05": p05.round(4).tolist(), "p50": p50.round(4).tolist(), "p95": p95.round(4).tolist()}


def place_result(name: str, place: str, ms, change: dict, target_year: int) -> dict:
    last = ms.time[np.isfinite(ms.value)].max()
    horizon = int(min(max(target_year - last.year, 5), 100))
    knobs, how = knobs_for(change, ms, horizon, last.year)
    sim = simulate({name: ms}, {name: knobs}, horizon_years=horizon, n_runs=N_RUNS, return_runs=True)
    ref = simulate({name: ms}, {}, horizon_years=horizon, n_runs=N_RUNS, return_runs=True)
    v, r = sim["variables"][name], ref["variables"][name]
    t = pd.DatetimeIndex(pd.to_datetime(v["time"]))
    years, with_change = _annual(v.pop("_runs"), t)
    _, without = _annual(r.pop("_runs"), t)
    b = v["baseline"]
    obs = pd.Series(ms.value, index=ms.time)
    counts = obs.groupby(obs.index.year).count()
    obs_year = obs.groupby(obs.index.year).mean()[counts >= 12]     # complete years only, gaps stay gaps
    trend_now = b["slope_per_decade"]
    trend_new = trend_now * knobs.get("trend_multiplier", 1.0) + knobs.get("trend_add_per_decade", 0.0)
    end_with, end_without = float(np.median(with_change[:, -1])), float(np.median(without[:, -1]))
    u = ms.units or ""
    lo, hi = np.percentile(with_change[:, -1] - without[:, -1], [5, 95])
    e05, e95 = np.percentile(with_change[:, -1], [5, 95])
    sentence = (f"In {place}, the observed record ({ms.time[0].year}-{last.year}) has a trend of "
                f"{trend_now:+.2f} {u} per decade (uncertainty ±{1.96 * b['slope_se_per_decade']:.2f}). "
                f"With {how}, the simulated trend becomes {trend_new:+.2f} {u} per decade, and the simulated annual "
                f"mean in {years[-1]} is {end_with:.1f} {u} (90% of simulated runs {e05:.1f} to {e95:.1f}) instead of "
                f"{end_without:.1f} {u} without the change, a difference of {end_with - end_without:+.1f} {u}.")
    return {
        "place": place, "variable": name, "units": u, "label": "simulated",
        "observed": {"years": [int(y) for y in obs_year.index], "annual_mean": [round(float(x), 4) for x in obs_year]},
        "simulated": {"years": years, "with_change": _band(with_change), "without_change": _band(without)},
        "trend_per_decade": {"observed": round(trend_now, 4), "observed_ci95": round(1.96 * b["slope_se_per_decade"], 4),
                             "with_change": round(trend_new, 4)},
        "end": {"year": years[-1], "with_change": round(end_with, 3), "without_change": round(end_without, 3),
                "difference": round(end_with - end_without, 3), "difference_range90": [round(lo, 3), round(hi, 3)],
                "with_change_range90": [round(e05, 3), round(e95, 3)]},
        "change_applied": how, "knobs": knobs, "plain_language": sentence,
        "baseline": {k: b[k] for k in ("slope_per_decade", "slope_se_per_decade", "lag1_autocorr", "residual_sd")
                     if k in b},
        "provenance": {"dataset": ms.provenance.dataset_short_name, "version": ms.provenance.version,
                       "source_api": ms.provenance.source_api, "doi": ms.provenance.doi,
                       "retrieved_at": ms.provenance.retrieved_at},
    }


async def run_whatif(st, question: str, progress) -> dict:
    from ..active.runner import _ineligible
    from ..core.geometry import parse_geometry
    from ..report.builder import _plan, candidate_variables, last_full_year

    await progress(0.03, "Reading the question")
    change = parse_change(question)
    if not change:
        raise InvalidRequest("Say what changes and by how much, for example '+2 °C by 2050', '+20% rainfall' or "
                             "'if warming doubled'.")
    plan = await _plan(st, question)
    regions = (plan.get("regions") or [])[:4]
    if not regions:
        raise InvalidRequest("Name at least one place, for example 'in Chennai and California'.")
    rank = {"giovanni": 0, "opendap": 1, "erddap": 2}      # gridded area means first: NASA, then keyless NOAA
    cands = sorted(candidate_variables(st, plan, None), key=lambda c: rank.get(st.catalog.variables[c].get("source"), 3))
    if not cands:
        raise InvalidRequest("Name the quantity that changes, for example temperature or rainfall.")
    y1 = last_full_year()
    start, end = date(y1 - BASE_YEARS + 1, 1, 1), date(y1, 12, 31)
    target = change["target_year"] or DEFAULT_TARGET_YEAR
    if target <= y1:
        raise InvalidRequest(f"The target year {target} is not in the future; the record ends in {y1}.")
    places, skipped = [], []
    for i, reg in enumerate(regions):
        region, name = parse_geometry(reg["geometry"]), reg.get("name") or f"place {i + 1}"
        info = vid = None
        attempts = []
        for c in cands:
            v = st.catalog.variables.get(c)
            why = _ineligible(v, region, start, end, {})
            if why or (change["unit"] == "°C" and v.get("family") not in ("temperature", None)):
                attempts.append(f"{c}: {why or 'not a temperature'}")
                continue
            await progress(0.08 + 0.8 * i / len(regions), f"Fetching {v['name']} for {name}")
            try:
                info, vid = await st.ts.build_series(c, region, start, end), c
                break
            except Exception as exc:  # noqa: BLE001 - try the next dataset for this place
                attempts.append(f"{c}: {getattr(exc, 'message', str(exc))[:160]}")
        if info is None:
            skipped.append({"place": name, "reason": "no dataset could be fetched", "attempts": attempts})
            continue
        ms = st.store.load(info["series_id"])
        await progress(0.12 + 0.8 * (i + 0.5) / len(regions), f"Simulating {name}")
        res = place_result(st.catalog.variables[vid]["name"], name, ms, change, target)
        res["variable_id"], res["series_id"] = vid, info["series_id"]
        places.append(res)
    if not places:
        raise InvalidRequest("None of the places could be fetched", detail={"skipped": skipped})
    note = ("You described a global change. It is applied to each place as stated; real local changes differ "
            "(land usually warms faster than the global average, oceans slower)." if change["scope"] == "global" else None)
    await progress(1.0, "Done")
    return {"question": question, "change": change, "target_year": target, "places": places, "skipped": skipped,
            "scope_note": note, "label": "simulated", "disclaimer": DISCLAIMER,
            "method": ("Each place's record is fitted with a seasonal cycle, a linear trend and AR(1) noise (twin "
                       "baseline), then simulated forward 400 times with and without the change; the same random noise is "
                       "used in both, so the difference shows only the change.")}
