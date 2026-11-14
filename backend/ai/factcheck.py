"""Numeric fact-check for AI text.

Every number in the model's text must match a number in the facts it was given (allowing for
rounding, sign words such as "falling by 0.3", percentages and per-decade/per-year scaling).
If any number cannot be traced, the AI text is rejected and the deterministic text is used.
"""
from __future__ import annotations

import math
import re

NUM = re.compile(r"(?<![\w.])[-−+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-−+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
SAFE_SMALL_INTS = set(range(0, 13))           # "two tests", "12 months", "5-year mean"


def extract_numbers(text: str) -> list[tuple[str, float]]:
    out = []
    for m in NUM.finditer(text or ""):
        s = m.group(0)
        try:
            out.append((s, float(s.replace(",", "").replace("−", "-"))))
        except ValueError:
            continue
    return out


def collect_fact_numbers(obj, acc: set | None = None) -> set[float]:
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for v in obj.values():
            collect_fact_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_fact_numbers(v, acc)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        if math.isfinite(obj):
            acc.add(float(obj))
    elif isinstance(obj, str):
        for _, v in extract_numbers(obj):
            acc.add(v)
    return acc


def _matches(x: float, facts: set[float]) -> bool:
    ax = abs(x)
    if x.is_integer() and ax in SAFE_SMALL_INTS:
        return True
    for f in facts:
        for cand in (f, f * 100.0, f / 10.0, f * 10.0):      # percent and per-year <-> per-decade
            af = abs(cand)
            if af == 0:
                if ax == 0:
                    return True
                continue
            if math.isclose(ax, af, rel_tol=1e-6):
                return True
            # x must be a correct rounding of the fact: 1..4 significant figures, or 0..3 decimals
            if ax > 0:
                mag = math.floor(math.log10(ax))
                for sig in range(1, 5):
                    half_unit = 0.5 * 10 ** (mag - sig + 1)
                    if abs(ax - af) <= half_unit * (1 + 1e-9):
                        return True
            for d in range(0, 4):
                if abs(round(af, d) - ax) < 1e-12:
                    return True
    return False


def fact_check(text: str, facts: dict | list) -> dict:
    allowed = collect_fact_numbers(facts)
    unsupported = []
    for raw, val in extract_numbers(text):
        if 1800 <= abs(val) <= 2200 and val.is_integer():     # a year: must be a year present in the facts
            if val not in allowed:
                unsupported.append(raw)
            continue
        if not _matches(val, allowed):
            unsupported.append(raw)
    return {"passed": not unsupported, "unsupported_numbers": unsupported, "n_numbers_checked":
            len(extract_numbers(text))}
