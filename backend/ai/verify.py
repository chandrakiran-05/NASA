"""Claim verifier for AI-written text (Trend Forensics: "the AI guesses, the data decides").

LLMs reason about raw time series barely above chance (Merrill et al. 2024, Findings of EMNLP,
arXiv:2404.11757), but checking a statement against known facts is far more reliable than
generating it. So the local model never computes anything: it only rephrases a FACTS object,
and every sentence it writes must pass these deterministic checks before a user sees it.

Checks
------
numbers        every number (and every year) must trace to FACTS          (factcheck.fact_check)
direction      words for rising/falling must match facts['direction']
significance   "significant"/"proven" claims must match facts['significant']
causation      no causal verbs ("caused", "because of", "driven by", "proves"): the tool only shows
               association; wording must be "consistent with" / "associated with"
forecast       future values must be called an extrapolation, never a prediction/forecast of climate
"""
from __future__ import annotations

import re

from .factcheck import fact_check

CAUSAL = re.compile(r"\b(caus(?:e|es|ed|ing)|because of|driven by|is driving|are driving|leads? to|led to|"
                    r"results? in|resulted in|proves?|proven|proof)\b", re.I)
RISE = re.compile(r"\b(ris(?:e|es|ing|en)|rose|increas\w*|grow\w*|warm(?:ing|er|ed)|wetter|upward|climb\w*|higher)\b", re.I)
FALL = re.compile(r"\b(fall\w*|fell|declin\w*|decreas\w*|drop\w*|shrink\w*|cool(?:ing|er|ed)|drier|downward|lower)\b", re.I)
SIG_CLAIM = re.compile(r"(?<!not )(?<!isn't )(?<!no )\bstatistically significant\b|\bis significant\b|"
                       r"\bsignificant (?:trend|rise|fall|increase|decrease|change)\b", re.I)
NOT_SIG = re.compile(r"\b(not (?:statistically )?significant|isn't significant|no significant|not proven|"
                     r"cannot (?:yet )?(?:say|tell|confirm)|not (?:yet )?confirmed)\b", re.I)
PREDICT = re.compile(r"\b(will (?:be|reach|rise|fall|increase|decrease)|predict\w*|forecast\w*)\b", re.I)
EXTRAPOLATION = re.compile(r"\b(extrapolat\w*|if (?:the )?(?:current )?(?:rate|trend)s? (?:persist|continue)s?)\b", re.I)


def _direction_check(text: str, facts: dict) -> dict:
    d = (facts.get("direction") or "").lower()
    up, down = len(RISE.findall(text)), len(FALL.findall(text))
    if d in ("rising", "increasing", "up") and down > 0 and up == 0:
        return {"passed": False, "detail": "text describes a fall but the computed trend is rising"}
    if d in ("falling", "decreasing", "down") and up > 0 and down == 0:
        return {"passed": False, "detail": "text describes a rise but the computed trend is falling"}
    return {"passed": True}


def _significance_check(text: str, facts: dict) -> dict:
    sig = facts.get("significant")
    if sig is False and SIG_CLAIM.search(text) and not NOT_SIG.search(text):
        return {"passed": False, "detail": "text calls the trend significant but the tests do not"}
    if sig is True and re.search(r"\b(not (?:statistically )?significant|isn't significant|no significant)\b",
                                 text, re.I):
        return {"passed": False, "detail": "text says not significant but the tests are significant"}
    return {"passed": True}


def _causation_check(text: str) -> dict:
    hits = sorted({m.group(0).lower() for m in CAUSAL.finditer(text)})
    if hits:
        return {"passed": False, "detail": f"causal wording not allowed: {hits}; use 'consistent with' or "
                                           f"'associated with'"}
    return {"passed": True}


def _forecast_check(text: str) -> dict:
    if PREDICT.search(text) and not EXTRAPOLATION.search(text):
        return {"passed": False, "detail": "future values must be described as a statistical extrapolation"}
    return {"passed": True}


def verify_text(text: str, facts: dict) -> dict:
    fc = fact_check(text, facts)
    checks = [
        {"name": "numbers", "passed": fc["passed"],
         **({} if fc["passed"] else {"detail": f"numbers not in the computed results: {fc['unsupported_numbers']}"})},
        {"name": "direction", **_direction_check(text, facts)},
        {"name": "significance", **_significance_check(text, facts)},
        {"name": "causation", **_causation_check(text)},
        {"name": "forecast_wording", **_forecast_check(text)},
    ]
    n_ok = sum(c["passed"] for c in checks)
    return {
        "passed": n_ok == len(checks),
        "checks": checks,
        "numbers_checked": fc["n_numbers_checked"],
        "unsupported_numbers": fc["unsupported_numbers"],
        "badge": f"{n_ok}/{len(checks)} checks passed · {fc['n_numbers_checked']} numbers traced to the data"
                 if n_ok == len(checks) else f"rejected: {', '.join(c['name'] for c in checks if not c['passed'])}",
        "fact_check": fc,
    }


def failure_feedback(v: dict) -> str:
    return "; ".join(c.get("detail", c["name"]) for c in v["checks"] if not c["passed"])
