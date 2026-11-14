#!/usr/bin/env python3
"""Speed benchmark of the analysis kernels vs common reference libraries.

    python scripts/benchmark.py
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from backend.analysis import kernels as K  # noqa: E402
from backend.analysis.engine import analyze_series  # noqa: E402
from backend.analysis.trend import mann_kendall, sens_slope  # noqa: E402
from backend.insights.cube import cube_trends  # noqa: E402
from backend.insights.engine import run_insights  # noqa: E402
from backend.timeseries.model import MonthlySeries, Provenance  # noqa: E402


def timeit(fn, reps=3):
    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def main() -> None:
    import pymannkendall as pmk
    from scipy import stats
    K.warmup()
    rng = np.random.default_rng(0)
    rows = []
    for n in (300, 3_000, 20_000):
        x = rng.normal(size=n)
        t = np.arange(n) / 12
        ours = timeit(lambda: mann_kendall(t, x, variant="original"))
        ref = timeit(lambda: pmk.original_test(x), reps=1) if n <= 20_000 else float("nan")
        rows.append(("Mann-Kendall test", n, ours, ref, "pymannkendall"))
    for n in (300, 2_000):
        x = rng.normal(size=n)
        t = np.arange(n) / 12
        rows.append(("Sen slope + CI", n, timeit(lambda: sens_slope(t, x)), timeit(lambda: stats.theilslopes(x, t)),
                     "scipy.theilslopes"))
    idx = pd.date_range("2001-01-01", periods=288, freq="MS")
    y = 20 + 5 * np.sin(2 * np.pi * idx.month.to_numpy() / 12) + 0.03 * np.arange(288) / 12 + rng.normal(0, 0.5, 288)
    ms = MonthlySeries(idx, y, "degC", Provenance("bench", "x", {}), label="bench")
    rows.append(("Full analysis (STL+OLS+MK+SMK+Sen)", 288, timeit(lambda: analyze_series(ms)), float("nan"), "-"))
    rows.append(("All insights incl. forecast CV", 288, timeit(lambda: run_insights(ms), reps=1), float("nan"), "-"))
    cube = rng.normal(0, 1, (288, 60, 80))
    rows.append(("Trend map 60x80 px x 288 months", 4800, timeit(lambda: cube_trends(cube, idx.month.to_numpy(),
                                                                               np.linspace(0, 10, 60),
                                                                               np.linspace(70, 80, 80)), reps=1),
                 float("nan"), "-"))
    print(f"{'operation':38s} {'n':>7s} {'ours (ms)':>11s} {'reference (ms)':>15s} {'speed-up':>9s}  reference")
    for name, n, ours, ref, refname in rows:
        su = f"{ref / ours:8.0f}x" if np.isfinite(ref) else "      -"
        rs = f"{ref * 1000:15.1f}" if np.isfinite(ref) else f"{'-':>15s}"
        print(f"{name:38s} {n:7d} {ours * 1000:11.2f} {rs} {su}  {refname}")


if __name__ == "__main__":
    main()
