"""Independent simulation study of the WHEN module (backend/insights/onset.py: change_onset).

Questions (results go to docs/BEAST-VALIDATION.md):
  1. false alarms : share of NO-change series (steady trend + AR(1) noise) with a "confirmed" change
  2. power        : share of series with a real slope change / level jump / both that are confirmed
                    within +/- 24 months of the true date
  3. dating       : |confirmed date - true date| (median, 90th pct) and coverage of interval90
  4. gate         : backend.active.engine.detect + beast_gate end to end on known recent directions
  5. baselines    : Pettitt (AR(1)-corrected, inside novelty.integrity.trend_or_jump) and PELT
                    (insights.changepoint.detect_trend_breaks, as the insights engine calls it),
                    run on the SAME series.

Synthetic series: seasonal cycle 1.5*sin + linear trend + AR(1) noise scaled to unit marginal SD,
so every effect size is in noise-SD units. change_onset runs with the API defaults (n_surrogates=49,
seed=2026, alpha=0.05). Every trial's data come from a fixed seed (crc32 of the cell name + trial),
so any single trial can be re-run alone.

Run:  python scripts/beast_validation.py            (full study, ~25 min on 10 processes)
      python scripts/beast_validation.py --quick    (smoke version, ~2 min)
      add --out results.json to keep the raw per-trial records.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.active.engine import beast_gate, detect  # noqa: E402
from backend.analysis.deseason import deseasonalize  # noqa: E402
from backend.insights.changepoint import detect_trend_breaks  # noqa: E402
from backend.insights.onset import change_onset  # noqa: E402
from backend.novelty.integrity import trend_or_jump  # noqa: E402
from backend.timeseries.model import MonthlySeries, Provenance  # noqa: E402

PHIS = [0.0, 0.3, 0.5, 0.7, 0.8]
BASE_SLOPE = 0.3          # noise-SD per decade, the steady background trend in every null/power series
HIT_MONTHS = 24           # a detection counts for power only within +/- 24 months of the truth
# effect sizes in noise-SD units: level jump (SD), slope change (SD per decade)
EFFECTS = [("slope", 0.0, 0.5), ("slope", 0.0, 1.0), ("slope", 0.0, 2.0),
           ("jump", 0.5, 0.0), ("jump", 1.0, 0.0), ("jump", 1.5, 0.0),
           ("both", 0.5, 0.5), ("both", 1.0, 1.0)]
# gate scenarios: (name, slope before, slope over the last 10 years [SD/decade], true recent direction)
GATE = [("steady_rise", 0.8, 0.8, "rising"), ("recent_reversal", 0.8, -1.5, "falling"),
        ("recent_acceleration", 0.3, 1.5, "rising"), ("no_trend", 0.0, 0.0, "none")]


# ------------------------------------------------------------------ data
def rng_for(key: str, trial: int) -> np.random.Generator:
    return np.random.default_rng([zlib.crc32(key.encode()), trial])


def ar1_unit(phi: float, n: int, rng: np.random.Generator) -> np.ndarray:
    z = rng.normal(size=n)
    e = np.empty(n)
    e[0] = z[0]
    s = math.sqrt(1 - phi * phi)
    for i in range(1, n):
        e[i] = phi * e[i - 1] + s * z[i]
    return e


def make(n: int, phi: float, rng: np.random.Generator, slope: float = BASE_SLOPE, kb: int | None = None,
         jump: float = 0.0, dslope: float = 0.0, miss: str = "none") -> np.ndarray:
    t = np.arange(n) / 12
    y = 1.5 * np.sin(2 * np.pi * t) + slope / 10 * t + ar1_unit(phi, n, rng)
    if kb is not None:
        after = np.arange(n) >= kb
        y = y + after * (jump + dslope / 10 * (t - t[kb]))
    if miss == "random10":
        y[rng.random(n) < 0.10] = np.nan
    elif miss == "block36":
        s = int(rng.integers(24, n - 60))
        y[s:s + 36] = np.nan
    return y


def to_ms(y: np.ndarray) -> MonthlySeries:
    return MonthlySeries(pd.date_range("2001-01-01", periods=len(y), freq="MS"), y, "sd",
                         Provenance("synthetic", "x", {}))


def midx(ym: str) -> int:
    y, m = ym.split("-")[:2]
    return (int(y) - 2001) * 12 + int(m) - 1


# ------------------------------------------------------------------ one trial
def run_detection(task: dict) -> dict:
    rng = rng_for(task["key"], task["trial"])
    n, phi = task["n"], task["phi"]
    kb = int(rng.integers(60, n - 60)) if task.get("type") else None
    y = make(n, phi, rng, kb=kb, jump=task.get("jump", 0.0), dslope=task.get("dslope", 0.0),
             miss=task.get("miss", "none"))
    ms = to_ms(y)
    t0 = time.perf_counter()
    o = change_onset(ms, n_surrogates=49)
    secs = time.perf_counter() - t0
    out = {"key": task["key"], "trial": task["trial"], "kb": kb, "secs": secs, "status": o["status"]}
    ev = o.get("events", [])
    conf = [e for e in ev if e["status"] == "confirmed"]
    out["phi_hat"] = (o.get("memory") or {}).get("lag1_autocorr")
    out["L"] = (o.get("memory") or {}).get("block_months")
    out["any_event"] = any(e["status"] in ("confirmed", "possible") for e in ev)
    out["p_cal_top"] = ev[0]["p_calibrated"] if ev else None
    out["confirmed"] = None
    if conf:
        e = conf[0]
        out["confirmed"] = {"k": midx(e["date"]), "lo": midx(e["interval90"][0]), "hi": midx(e["interval90"][1]),
                            "p": e["p_calibrated"], "prob": e["probability"]}
    a = deseasonalize(ms, "stl").deseasonalized          # what integrity + insights hand to the baselines
    t = ms.t_years()
    tj = trend_or_jump(t, a, ms.time)
    out["pettitt"] = {"p": tj.get("pettitt_p"), "k": midx(tj["pettitt_date"]) if tj.get("pettitt_date") else None,
                      "best": tj.get("best_model")}
    br = detect_trend_breaks(ms.time, t, a, min_segment_years=4.0, alpha=0.05)
    out["pelt"] = {"ks": [b["index"] for b in br.get("breaks", [])], "bic": bool(br.get("segmented_preferred"))}
    return out


def run_gate(task: dict) -> dict:
    rng = rng_for(task["key"], task["trial"])
    n, phi = 288, task["phi"]
    kb = n - 120
    y = make(n, phi, rng, slope=task["s0"], kb=kb, dslope=task["s1"] - task["s0"])
    ms = to_ms(y)
    det = detect(ms)
    o = change_onset(ms, n_surrogates=49)
    g = beast_gate(o, det) if det.get("direction") else {"status": "skipped"}
    p = o.get("current_direction_probability") or {}
    return {"key": task["key"], "trial": task["trial"], "state": det["state"], "active": det.get("active"),
            "direction": det.get("direction"), "gate": g["status"], "p_rising": p.get("rising"),
            "p_falling": p.get("falling"), "n_confirmed": sum(e["status"] == "confirmed" for e in o.get("events", []))}


def run(task: dict) -> dict:
    try:
        return run_gate(task) if task["kind"] == "gate" else run_detection(task)
    except Exception as exc:  # noqa: BLE001 - a crash is itself a finding; keep the rest of the study
        return {"key": task["key"], "trial": task["trial"], "error": repr(exc)}


# ------------------------------------------------------------------ plan
def plan(quick: bool) -> list[dict]:
    phis = [0.0, 0.7] if quick else PHIS
    n_null, n_pow, n_gate = (4, 4, 4) if quick else (60, 40, 40)
    tasks = []
    for n in (288, 180):
        for miss in ("none", "random10", "block36"):
            for phi in phis:
                key = f"null|n={n}|miss={miss}|phi={phi}"
                tasks += [{"kind": "null", "key": key, "n": n, "phi": phi, "miss": miss, "trial": i}
                          for i in range(n_null)]
    for typ, jump, ds in EFFECTS:
        for phi in phis:
            key = f"power|{typ}|jump={jump}|dslope={ds}|phi={phi}"
            tasks += [{"kind": "power", "key": key, "n": 288, "phi": phi, "type": typ, "jump": jump,
                       "dslope": ds, "trial": i} for i in range(n_pow)]
    for name, s0, s1, truth in GATE:
        for phi in ([0.5] if quick else [0.3, 0.7]):
            key = f"gate|{name}|phi={phi}"
            tasks += [{"kind": "gate", "key": key, "phi": phi, "s0": s0, "s1": s1, "truth": truth, "trial": i}
                      for i in range(n_gate)]
    return tasks


# ------------------------------------------------------------------ summaries
def ci(k: int, n: int) -> str:
    """Rate with exact (Clopper-Pearson) 95% interval, in percent."""
    if n == 0:
        return "n/a"
    lo = stats.beta.ppf(0.025, k, n - k + 1) if k > 0 else 0.0
    hi = stats.beta.ppf(0.975, k + 1, n - k) if k < n else 1.0
    return f"{100 * k / n:.0f}% [{100 * lo:.0f}-{100 * hi:.0f}] ({k}/{n})"


def near(k, kb) -> bool:
    return k is not None and abs(k - kb) <= HIT_MONTHS


def pct(x, q):
    return f"{np.percentile(x, q):.0f}" if len(x) else "-"


def summarize(res: list[dict], tasks: list[dict]) -> str:
    meta = {}
    for t in tasks:
        meta.setdefault(t["key"], t)
    by = {}
    for r in res:
        by.setdefault(r["key"], []).append(r)
    errs = [r for r in res if "error" in r]
    lines = []
    if errs:
        lines += [f"**{len(errs)} trials raised an exception**, e.g. `{errs[0]['key']}` trial {errs[0]['trial']}: "
                  f"`{errs[0]['error']}`", ""]

    # --- Q1 false alarms
    lines += ["### Q1. False alarms on series with no change (target about 5%)", "",
              "| months | missing | phi | median phi-hat | BEAST confirmed | BEAST confirmed or possible | "
              "Pettitt p<0.05 | Pettitt jump flag (integrity) | PELT any break | PELT BIC-preferred |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    pooled = {}
    for key, rs in by.items():
        m = meta[key]
        if m["kind"] != "null":
            continue
        rs = [r for r in rs if "error" not in r]
        N = len(rs)
        c = sum(r["confirmed"] is not None for r in rs)
        pooled.setdefault(m["miss"], [0, 0])
        pooled[m["miss"]][0] += c
        pooled[m["miss"]][1] += N
        ph = [r["phi_hat"] for r in rs if r["phi_hat"] is not None]
        pt = [r["pettitt"] for r in rs]
        lines.append(
            f"| {m['n']} | {m['miss']} | {m['phi']} | {np.median(ph):.2f} | {ci(c, N)} | "
            f"{ci(sum(r['any_event'] for r in rs), N)} | "
            f"{ci(sum((p['p'] or 1) < 0.05 for p in pt), N)} | "
            f"{ci(sum((p['p'] or 1) < 0.05 and p['best'] == 'jump' for p in pt), N)} | "
            f"{ci(sum(bool(r['pelt']['ks']) for r in rs), N)} | {ci(sum(r['pelt']['bic'] for r in rs), N)} |")
    nul = [r for r in res if meta[r["key"]]["kind"] == "null" and "error" not in r]
    lines += ["", "Pooled BEAST false-alarm rate by missing-data pattern: " +
              "; ".join(f"{k}: {ci(*v)}" for k, v in pooled.items()), "",
              "Pooled by phi (both lengths, all missing patterns), BEAST confirmed vs PELT BIC-preferred: " +
              "; ".join(f"phi {ph}: {ci(sum(r['confirmed'] is not None for r in s), len(s))} vs "
                        f"{ci(sum(r['pelt']['bic'] for r in s), len(s))}"
                        for ph in sorted({meta[r['key']]['phi'] for r in nul})
                        for s in [[r for r in nul if meta[r['key']]['phi'] == ph]]), "",
              f"All {len(nul)} no-change series: BEAST confirmed {ci(sum(r['confirmed'] is not None for r in nul), len(nul))}; "
              f"BEAST confirmed or possible {ci(sum(r['any_event'] for r in nul), len(nul))}; "
              f"PELT BIC-preferred {ci(sum(r['pelt']['bic'] for r in nul), len(nul))}; "
              f"PELT any break {ci(sum(bool(r['pelt']['ks']) for r in nul), len(nul))}; "
              f"Pettitt jump flag {ci(sum((r['pettitt']['p'] or 1) < 0.05 and r['pettitt']['best'] == 'jump' for r in nul), len(nul))}.", ""]

    # --- Q2/Q3 power and dating
    lines += ["### Q2-Q3. Power (detection within +/-24 months of the true date) and dating error", "",
              "Effect sizes in noise-SD units (jump) and noise-SD per decade (slope change); 288 months; "
              "break month uniform in [60, 228].", "",
              "| change | jump | slope chg | phi | BEAST power | PELT power (BIC-preferred) | PELT power (any break) | "
              "Pettitt power (p<0.05) | Pettitt power (jump flag) | BEAST abs err median/P90 (mo) | "
              "Pettitt err med/P90 | PELT err med/P90 | interval90 coverage |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    allerr = {"beast": [], "pettitt": [], "pelt": []}
    cov = [0, 0]
    for key, rs in by.items():
        m = meta[key]
        if m["kind"] != "power":
            continue
        rs = [r for r in rs if "error" not in r]
        N = len(rs)
        eb, ep, el = [], [], []
        hb = hp = hl = hlb = hpj = 0
        kc = kn = 0
        for r in rs:
            kb = r["kb"]
            c = r["confirmed"]
            if c:
                eb.append(abs(c["k"] - kb))
                hb += near(c["k"], kb)
                kn += 1
                kc += c["lo"] <= kb <= c["hi"]
            pt = r["pettitt"]
            if (pt["p"] or 1) < 0.05 and pt["k"] is not None:
                ep.append(abs(pt["k"] - kb))
                hp += near(pt["k"], kb)
                hpj += near(pt["k"], kb) and pt["best"] == "jump"
            if r["pelt"]["ks"]:
                d = min(abs(k - kb) for k in r["pelt"]["ks"])
                el.append(d)
                hl += d <= HIT_MONTHS
                hlb += d <= HIT_MONTHS and r["pelt"]["bic"]
        allerr["beast"] += eb
        allerr["pettitt"] += ep
        allerr["pelt"] += el
        cov[0] += kc
        cov[1] += kn
        lines.append(f"| {m['type']} | {m['jump']} | {m['dslope']} | {m['phi']} | {ci(hb, N)} | {ci(hlb, N)} | "
                     f"{ci(hl, N)} | {ci(hp, N)} | {ci(hpj, N)} | {pct(eb, 50)}/{pct(eb, 90)} | {pct(ep, 50)}/{pct(ep, 90)} | "
                     f"{pct(el, 50)}/{pct(el, 90)} | {ci(kc, kn)} |")
    lines += ["", "Pooled over all power cells (every detection, not only those within 24 months): "
              f"BEAST |error| median {pct(allerr['beast'], 50)}, P90 {pct(allerr['beast'], 90)} months "
              f"(n={len(allerr['beast'])}); Pettitt {pct(allerr['pettitt'], 50)}/{pct(allerr['pettitt'], 90)} "
              f"(n={len(allerr['pettitt'])}); PELT nearest break {pct(allerr['pelt'], 50)}/"
              f"{pct(allerr['pelt'], 90)} (n={len(allerr['pelt'])}). interval90 coverage pooled: {ci(*cov)}.", ""]

    # --- Q4 gate
    lines += ["### Q4. Active-trend detect + beast_gate end to end (288 months, change 120 months before the end)",
              "", "| scenario | true recent dir. | phi | detect active | detect dir. correct | gate agrees | "
              "gate disagrees | gate uncertain | active AND agrees AND dir. correct | active AND agrees AND dir. wrong |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for key, rs in by.items():
        m = meta[key]
        if m["kind"] != "gate":
            continue
        rs = [r for r in rs if "error" not in r]
        N = len(rs)
        ok = [r["direction"] == m["truth"] for r in rs]
        agr = [r["gate"] == "agrees" for r in rs]
        act = [bool(r["active"]) for r in rs]
        lines.append(
            f"| {m['key'].split('|')[1]} | {m['truth']} | {m['phi']} | {ci(sum(act), N)} | "
            f"{ci(sum(ok), N) if m['truth'] != 'none' else 'n/a'} | {ci(sum(agr), N)} | "
            f"{ci(sum(r['gate'] == 'disagrees' for r in rs), N)} | {ci(sum(r['gate'] == 'uncertain' for r in rs), N)} | "
            f"{ci(sum(a and g and o for a, g, o in zip(act, agr, ok)), N)} | "
            f"{ci(sum(a and g and not o for a, g, o in zip(act, agr, ok)), N)} |")
    secs = [r["secs"] for r in res if "secs" in r]
    lines += ["", f"change_onset wall time per call: median {np.median(secs):.1f} s (n={len(secs)})."]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="2-minute smoke version (few trials, 2 phi values)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--out", help="write per-trial records as JSON here")
    ap.add_argument("--summarize", help="re-print the tables from a JSON written by --out (no simulation)")
    args = ap.parse_args()
    tasks = plan(args.quick)
    if args.summarize:
        print(summarize(json.loads(Path(args.summarize).read_text()), tasks))
        return
    t0 = time.time()
    # processes, not threads: Rbeast holds the GIL
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(run, tasks, chunksize=2))
    print(f"{len(tasks)} trials, {args.workers} processes, {(time.time() - t0) / 60:.1f} min\n")
    print(summarize(res, tasks))
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
