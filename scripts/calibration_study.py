#!/usr/bin/env python3
"""Reproduce the false-positive (type-I error) table in docs/STATISTICS.md.

Simulates trend-free AR(1) monthly noise and counts how often each test wrongly reports a
significant trend at alpha = 0.05. A well-calibrated test should stay near 0.05.

    python scripts/calibration_study.py --trials 400
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")
from backend.analysis.trend import mann_kendall, ols_trend  # noqa: E402

TESTS = {
    "OLS naive": lambda t, y: ols_trend(t, y).p,
    "OLS AR(1)-adj": lambda t, y: ols_trend(t, y).p_adj,
    "MK original": lambda t, y: mann_kendall(t, y, variant="original").p,
    "MK Hamed-Rao*": lambda t, y: mann_kendall(t, y, variant="hamed_rao").p,
    "MK Yue-Wang*": lambda t, y: mann_kendall(t, y, variant="yue_wang").p,
    "MK TFPW*": lambda t, y: mann_kendall(t, y, variant="tfpw").p,
    "MK ess_ar1 (auto)": lambda t, y: mann_kendall(t, y, variant="ess_ar1").p,
}


def ar1(n, phi, rng):
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = phi * e[i - 1] + rng.normal()
    return e


def main(trials: int, n: int) -> None:
    rng = np.random.default_rng(2026)
    print(f"type-I error at alpha=0.05, n={n} months, {trials} simulations per cell (* = pymannkendall default)")
    print(f"{'phi':>5} | " + " ".join(f"{k:>17s}" for k in TESTS))
    for phi in (0.0, 0.3, 0.5, 0.7, 0.85):
        cnt = dict.fromkeys(TESTS, 0)
        for _ in range(trials):
            y = ar1(n, phi, rng)
            t = np.arange(n) / 12
            for k, f in TESTS.items():
                cnt[k] += f(t, y) < 0.05
        print(f"{phi:>5} | " + " ".join(f"{cnt[k] / trials:>17.3f}" for k in TESTS))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=400)
    ap.add_argument("--n", type=int, default=240)
    a = ap.parse_args()
    main(a.trials, a.n)
