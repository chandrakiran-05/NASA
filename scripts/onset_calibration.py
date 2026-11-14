"""Calibration study for the WHEN module (backend/insights/onset.py).

Measures, on synthetic monthly series with AR(1) noise:
  * false-alarm rate : share of steady-trend series (no change) where a change is "confirmed"
  * power            : share of series with a real break (level jump + slope change at month 144)
                       where a change is confirmed within +/- 24 months of the truth
  * raw BEAST        : the same false-alarm measure for BEAST run directly on monthly data
                       (window probability >= 0.8), to show why the safeguards are needed.

Run:  python scripts/onset_calibration.py [--trials 25]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.insights import onset  # noqa: E402
from backend.timeseries.model import MonthlySeries, Provenance  # noqa: E402

N = 288
IDX = pd.date_range("2001-01-01", periods=N, freq="MS")
T = np.arange(N) / 12


def ar1(phi: float, rng: np.random.Generator) -> np.ndarray:
    e = np.zeros(N)
    for i in range(1, N):
        e[i] = phi * e[i - 1] + rng.normal()
    return e


def series(y: np.ndarray) -> MonthlySeries:
    return MonthlySeries(IDX, y, "x", Provenance("synthetic", "x", {}))


def raw_beast_false_alarm(y: np.ndarray) -> bool:
    with onset._quiet_unraisable():
        o = onset._rb.beast(y, start=2001.0, deltat=1 / 12, period=1.0, season="harmonic", quiet=1,
                            print_progress=0, print_options=0, mcmc_seed=7)
    w = np.convolve(np.nan_to_num(o.trend.cpOccPr), np.ones(25), "same")
    return bool(w.max() >= 0.8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=25)
    ap.add_argument("--phis", type=float, nargs="+", default=[0.0, 0.5, 0.7, 0.8])
    args = ap.parse_args()
    print(f"{'phi':>4} | raw BEAST false alarms | calibrated false alarms | calibrated power")
    for phi in args.phis:
        rng = np.random.default_rng(100)
        raw_fa = fa = power = 0
        for i in range(args.trials):
            base = 2 * np.sin(2 * np.pi * T) + 0.03 * T + 0.4 * ar1(phi, rng)
            raw_fa += raw_beast_false_alarm(base)
            r0 = onset.change_onset(series(base), seed=i)
            fa += any(e["status"] == "confirmed" for e in r0["events"])
            brk = base + np.where(T >= 12, 0.6 + 0.1 * (T - 12), 0.0)
            r1 = onset.change_onset(series(brk), seed=i)
            power += any(e["status"] == "confirmed" and
                         abs((pd.Timestamp(e["date"] + "-01") - IDX[144]).days) <= 24 * 30.5 for e in r1["events"])
        k = args.trials
        print(f"{phi:>4} | {raw_fa:>10}/{k:<11} | {fa:>11}/{k:<11} | {power:>7}/{k}")


if __name__ == "__main__":
    main()
