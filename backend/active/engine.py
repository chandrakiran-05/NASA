"""Active trends: is a variable changing NOW, and does that survive independent checks?

A full-record trend can be history: a lake that fell for 20 years and has been steady since still
shows a "significant decline". The challenge asks what is changing, so this module tests the recent
part of the record against the part before it.

Stage A  detect     (milliseconds) recent window of W = clip(N/3, 10, 15) years vs the years before
                    it. Both are tested with AR(1)-corrected Mann-Kendall + AR(1)-adjusted OLS (the
                    Trend Court's default pair, false-positive rate ~5% in persistent data).
                    state: active | accelerating | emerging | reversed | stalled | none | too_short
Stage B  verify     independent checks on each candidate, run concurrently (runner.py):
                    integrity (F1 seams/jumps), court (F3 jurors on the recent window), chance (F5
                    block bootstrap), window stability (does it hinge on the chosen start year?),
                    plus cross-variable physics coherence and second opinion (same quantity, other
                    product) when several variables are scanned.
Stage C  BEAST      calibrated BEAST (insights/onset.py) must agree on the current direction: the
                    slope of the regime after its last confirmed change point, or its posterior slope
                    sign over the last year. A confirmed change point dates when the regime began.

Label    VERIFIED      no check failed, >= 3 passed, BEAST agrees, regime start not at a seam
         PROBABLE      no check failed, but BEAST is uncertain/skipped or there is a warning
         NOT VERIFIED  a check failed or BEAST disagrees
"VERIFIED" means the trend survived these checks on this data; it is not proof of a cause, and it
does not mean the trend will continue.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from ..analysis.deseason import deseasonalize
from ..analysis.trend import mann_kendall, ols_trend, sens_slope
from ..core.wording import TEST_NOTE, data_note
from ..timeseries.model import MonthlySeries

MIN_YEARS = 15
ACTIVE_STATES = ("active", "accelerating", "emerging", "reversed")
LIMIT = ("VERIFIED means the trend survived these checks on this data. It does not show what causes it, "
         "and it does not mean the trend will continue. PROBABLE or NOT VERIFIED means the trend is not clear "
         "enough to pass every check; the data themselves are still real measurements or model output.")


def window_years(n_years: float) -> int:
    return int(np.clip(round(n_years / 3), 10, 15))


def sub(ms: MonthlySeries, i: int, j: int | None = None) -> MonthlySeries:
    return MonthlySeries(time=ms.time[i:j], value=ms.value[i:j], units=ms.units, provenance=ms.provenance,
                         variable_id=ms.variable_id, series_id=ms.series_id, label=ms.label)


def _test(t: np.ndarray, a: np.ndarray, alpha: float) -> dict:
    o = ols_trend(t, a, alpha)
    mk = mann_kendall(t, a, alpha, "ess_ar1")
    sen = sens_slope(t, a, alpha)
    return {"slope_per_decade": sen.slope * 10, "ci95_per_decade": [sen.ci95[0] * 10, sen.ci95[1] * 10],
            "ols_slope": o.slope, "ols_se_adj": o.se_adj, "p_mk": mk.p, "p_ols_adj": o.p_adj,
            "p": max(mk.p, o.p_adj), "significant": bool(mk.p < alpha and o.p_adj < alpha)}


def _span(ms: MonthlySeries, i: int, j: int) -> str:
    return f"{ms.time[i].year}–{ms.time[j - 1].year}"


def _note(ms: MonthlySeries) -> str:
    p = ms.provenance
    return data_note(getattr(p, "source_api", None), ms.n, ms.n_valid, getattr(p, "dataset_short_name", None))


def detect(ms: MonthlySeries, alpha: float = 0.05) -> dict:
    n = ms.n
    n_years = n / 12
    if n_years < MIN_YEARS or ms.n_valid < MIN_YEARS * 12 * 0.7:
        return {"state": "too_short", "active": False, "data_note": _note(ms),
                "plain_language": f"Active-trend detection needs at least {MIN_YEARS} years of mostly complete "
                                  f"monthly data; this record has {ms.n_valid} months with a value. The data are "
                                  f"real; there are just not enough months yet for this test."}
    a = deseasonalize(ms, "stl").deseasonalized
    t = ms.t_years()
    W = window_years(n_years)
    k = n - W * 12
    full, recent, before = _test(t, a, alpha), _test(t[k:], a[k:], alpha), _test(t[:k], a[:k], alpha)
    # is the recent slope different from the earlier one? (AR(1)-adjusted standard errors)
    z = (recent["ols_slope"] - before["ols_slope"]) / math.hypot(recent["ols_se_adj"], before["ols_se_adj"])
    p_change = float(2 * stats.norm.sf(abs(z)))
    r, b = recent["slope_per_decade"], before["slope_per_decade"]
    same = np.sign(r) == np.sign(b)
    if recent["significant"]:
        if before["significant"] and same:
            state = "accelerating" if abs(r) > abs(b) and p_change < alpha else "active"
        elif before["significant"]:
            state = "reversed"
        else:
            state = "emerging"
    else:
        state = "stalled" if full["significant"] else "none"
    direction = "rising" if r > 0 else "falling" if r < 0 else "flat"
    sd = float(np.nanstd(a))
    u = ms.units or "units"
    rw, bw = _span(ms, k, n), _span(ms, 0, k)
    word = {"rising": "Rising", "falling": "Falling", "flat": "Flat"}[direction]
    txt = {
        "active": f"{word} now: {r:+.3g} {u} per decade over {rw}, continuing the trend of {bw} ({b:+.3g}).",
        "accelerating": f"{word} faster now: {r:+.3g} {u} per decade over {rw}, against {b:+.3g} over {bw}.",
        "emerging": f"{word} now: {r:+.3g} {u} per decade over {rw}; no trend was detectable over {bw}.",
        "reversed": f"Reversed: {r:+.3g} {u} per decade over {rw}, after {b:+.3g} over {bw}.",
        "stalled": f"The full record trends ({full['slope_per_decade']:+.3g} {u} per decade), but no trend is "
                   f"detectable over the last {W} years ({rw}).",
        "none": f"No detectable trend over {rw} or over the full record.",
    }[state]
    return {"state": state, "active": state in ACTIVE_STATES, "direction": direction,
            "rate_per_decade": r, "units": ms.units, "window_years": W,
            "recent_window": {"start": ms.time[k].strftime("%Y-%m"), "end": ms.time[-1].strftime("%Y-%m")},
            "recent": recent, "before": before, "full": full, "p_slope_change": p_change,
            "effect_sd_per_decade": abs(r) / sd if sd > 0 else None, "plain_language": txt, "data_note": _note(ms)}


# ------------------------------------------------------------------ stage B: single-series checks
def make_check(name: str, status: str, text: str, **detail) -> dict:
    return {"check": name, "status": status, "plain_language": text, "detail": detail}


def check_integrity(ms: MonthlySeries, det: dict) -> dict:
    from ..novelty.integrity import integrity_audit
    aud = integrity_audit(ms, deseasonalize(ms, "stl").deseasonalized)
    ws = det["recent_window"]["start"]
    seams = [s for s in aud["seams"] if s.get("significant") and s["date"] >= f"{int(ws[:4]) - 2}{ws[4:]}"]
    jump = aud["trend_or_jump"]
    jump_recent = (jump.get("best_model") == "jump" and jump.get("pettitt_p", 1) < 0.05
                   and (jump.get("pettitt_date") or "") >= ws)
    if aud["badge"] == "NOT_FIT":
        return make_check("integrity", "fail", "Not ready for a trend test (this is about the test, not whether the data are real): "
                          + " ".join(aud["reasons"]),
                      badge=aud["badge"])
    if seams:
        return make_check("integrity", "warn", f"Possible instrument effect at {seams[0]['date']} "
                      f"({seams[0]['event']}), at or near the start of the recent window.", badge=aud["badge"],
                      seams=[s["date"] for s in seams])
    if jump_recent:
        return make_check("integrity", "warn", "A single jump explains the recent window better than a steady trend: "
                      + jump.get("plain_language", ""), badge=aud["badge"])
    return make_check("integrity", "pass" if aud["badge"] == "OK" else "warn", " ".join(aud["reasons"]), badge=aud["badge"])


def check_court(ms: MonthlySeries, det: dict, alpha: float) -> dict:
    from ..novelty.court import court
    c = court(sub(ms, -det["window_years"] * 12), alpha)
    sen = next(j for j in c["jurors"] if j["id"] == "sen_ci")["slope_per_decade"]
    if c["stamp"] != "SIGNIFICANT":
        return make_check("court", "fail", f"Trend Court on the recent window: NOT PROVEN ({c['jurors_significant']} of "
                      f"{len(c['jurors'])} tests significant). The recent trend is not clear enough yet; "
                      f"the data are still real.", stamp=c["stamp"], chosen_test=c["chosen_test"])
    if np.sign(sen) != np.sign(det["rate_per_decade"]):
        return make_check("court", "fail", "Trend Court finds the opposite direction on the recent window, so the direction is unclear.", stamp=c["stamp"])
    return make_check("court", "warn" if c["flips"] else "pass",
                  f"Trend Court on the recent window: SIGNIFICANT ({c['jurors_significant']} of {len(c['jurors'])} "
                  f"tests agree; chosen test {c['chosen_test']}).", stamp=c["stamp"], flips=c["flips"])


def check_chance(ms: MonthlySeries, det: dict, alpha: float, n_null: int = 499) -> dict:
    from ..novelty.nulls import null_lineup
    r = null_lineup(sub(ms, -det["window_years"] * 12), n_null=n_null, n_panels=0)
    return make_check("chance", "pass" if r["perm_p"] < alpha else "fail",
                  f"{r['plain_language']} Simulated from your data, not observations.", perm_p=r["perm_p"])


def check_stability(ms: MonthlySeries, det: dict, alpha: float) -> dict:
    """Same answer if the window starts a little earlier/later or ends a year earlier? (anti cherry-picking)"""
    a = deseasonalize(ms, "stl").deseasonalized
    t = ms.t_years()
    n, W = ms.n, det["window_years"]
    want = np.sign(det["rate_per_decade"])
    windows = [(n - w * 12, n) for w in (W - 2, W - 1, W + 1, W + 2) if 8 <= w <= n / 12 - 5] + [(n - (W + 1) * 12, n - 12)]
    hits = []
    for i, j in windows:
        r = _test(t[i:j], a[i:j], alpha)
        hits.append(bool(r["significant"] and np.sign(r["slope_per_decade"]) == want))
    frac = sum(hits) / len(hits)
    status = "pass" if frac >= 0.6 else "warn" if frac >= 0.4 else "fail"
    return make_check("stability", status, f"{sum(hits)} of {len(hits)} nearby windows give the same significant "
                  f"direction" + ("." if status == "pass" else "; the result depends on the chosen years."),
                  fraction=frac)


def check_llm_note(review: dict | None) -> dict:
    if not review:
        return make_check("ai_review", "skipped", "Local AI reviewer not available.")
    return make_check("ai_review", "warn" if review.get("concerns") else "pass",
                  review.get("note") or "AI reviewer raised no concern.", concerns=review.get("concerns", []),
                  advisory=True)


# ------------------------------------------------------------------ stage B: cross-variable checks
def check_physics(vid: str, dets: dict[str, dict], links: list[dict]) -> dict:
    """Do linked variables that are also active move in the expected directions? (sign only)"""
    sign = {v: np.sign(d["rate_per_decade"]) for v, d in dets.items() if d.get("active")}
    rows = []
    for ln in links:
        if vid in (ln["a"], ln["b"]):
            other = ln["b"] if ln["a"] == vid else ln["a"]
            if other in sign and vid in sign:
                rows.append({"with": other, "consistent": bool(sign[vid] * sign[other] == ln["expected_sign"]),
                             "why": ln["why"]})
    if not rows:
        return make_check("physics", "skipped", "No linked variable with an active trend in this scan.")
    bad = [r for r in rows if not r["consistent"]]
    return make_check("physics", "warn" if bad else "pass",
                  (f"Not consistent with {', '.join(r['with'] for r in bad)}: worth investigating (local drivers, "
                   f"data issues, irrigation)." if bad else
                   f"Consistent with {', '.join(r['with'] for r in rows)}.") + " Sign check only, not a cause.",
                  links=rows)


def check_second_opinion(vid: str, dets: dict[str, dict], groups: list[dict]) -> dict:
    """Another product measuring the same quantity, scanned in the same run, agrees on the direction?"""
    for g in groups:
        members = g.get("members", []) + g.get("sign_only", [])
        if vid in members:
            others = [(o, dets[o]) for o in members if o != vid and o in dets and dets[o].get("state") != "too_short"]
            if not others:
                break
            me = np.sign(dets[vid]["rate_per_decade"])
            agree = [o for o, d in others if np.sign(d["rate_per_decade"]) == me and d["recent"]["significant"]]
            disputed = [o for o, d in others if np.sign(d["rate_per_decade"]) != me and d["recent"]["significant"]]
            status = "warn" if disputed else "pass" if agree else "warn"
            text = (f"Disputed: {', '.join(disputed)} shows a significant opposite trend." if disputed else
                    f"Same direction in {', '.join(agree)}." if agree else
                    "Other products of this quantity show a different direction (not significant).")
            return make_check("second_opinion", status, text, agree=agree, disputed=disputed)
    return make_check("second_opinion", "skipped", "No second product of this quantity in this scan.")


# ------------------------------------------------------------------ stage C: BEAST gate
def beast_gate(onset: dict, det: dict) -> dict:
    if onset.get("status") != "ok":
        return {"status": "skipped", "agrees": None, "plain_language": onset.get("plain_language", "BEAST not run.")}
    want = 1 if det["direction"] == "rising" else -1
    p = onset["current_direction_probability"]
    p_dir, p_opp = (p["rising"], p["falling"]) if want > 0 else (p["falling"], p["rising"])
    confirmed = [e for e in onset["events"] if e["status"] == "confirmed"]
    regime = confirmed[-1] if confirmed else None
    segs = onset.get("segments") or []
    last = segs[-1] if confirmed and len(segs) == len(confirmed) + 1 else None
    verdict = "uncertain"
    if last and last["significant"]:
        verdict = "agrees" if np.sign(last["slope_per_decade"]) == want else "disagrees"
    elif p_dir >= 0.6:
        verdict = "agrees"
    elif p_opp >= 0.6:
        verdict = "disagrees"
    since = None
    if regime:
        since = {"date": regime["date"], "interval90": regime["interval90"], "probability": regime["probability"],
                 "kind": regime.get("kind"), "near_seam": regime.get("near_seam"),
                 "agrees_with_pelt": regime.get("agrees_with_pelt")}
    txt = {"agrees": "BEAST agrees on the current direction",
           "disagrees": "BEAST does not support this direction",
           "uncertain": "BEAST cannot tell the current direction"}[verdict]
    txt += f" (model probability {p_dir:.0%} for {det['direction']} over the last year)"
    if since:
        txt += (f"; the current regime began around {since['date']} (approximate interval {since['interval90'][0]} to "
                f"{since['interval90'][1]})")
        if since["agrees_with_pelt"]:
            txt += "; PELT finds a break within two years of it too"
        if since["near_seam"]:
            txt += ", next to a possible instrument effect"
    return {"status": verdict, "agrees": verdict == "agrees", "p_direction": p_dir, "active_since": since,
            "plain_language": txt + "."}


def label(det: dict, checks: list[dict], beast: dict | None) -> dict:
    deterministic = [c for c in checks if c["check"] != "ai_review"]
    fails = [c["check"] for c in deterministic if c["status"] == "fail"]
    passes = [c["check"] for c in deterministic if c["status"] == "pass"]
    warns = [c["check"] for c in deterministic if c["status"] == "warn"]
    seam = bool(beast and (beast.get("active_since") or {}).get("near_seam"))
    if fails or (beast and beast["status"] == "disagrees"):
        lab = "NOT VERIFIED"
        why = f"did not pass: {', '.join(fails or ['BEAST direction'])}"
    elif beast and beast["agrees"] and len(passes) >= 3 and not seam and "integrity" not in warns and "fdr" not in warns:
        lab = "VERIFIED"
        why = f"passed {len(passes)} of {len(deterministic)} checks and BEAST agrees"
    else:
        lab = "PROBABLE"
        why = ", ".join(filter(None, [f"warnings: {', '.join(warns)}" if warns else "",
                                      "BEAST " + (beast["status"] if beast else "not run") if not (beast and beast["agrees"]) else "",
                                      "regime starts at a possible instrument effect" if seam else ""])) or "too few checks passed"
    return {"label": lab, "why": why, "passed": passes, "warnings": warns, "failed": fails,
            "plain_language": f"{lab}: {det['plain_language']} ({why}).", "limit": LIMIT,
            "test_note": TEST_NOTE, "data_note": det.get("data_note")}
