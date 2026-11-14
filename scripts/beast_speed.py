"""Speed audit of backend/insights/onset.change_onset (results in docs/BEAST-SPEED.md).

Read-only: it imports the backend and never edits it. Each candidate speed-up is an exact text patch
(PATCHES below) applied to an in-memory copy of onset.py, so the diff shown in the doc is the code tested.

Sections (all by default, or pick with --only):
  profile   where one call spends its time; scaling with series length and K
  identity  candidate patches vs current code on >= 20 random series (with missing months): bit-identical?
  speed     median wall-clock per call for each candidate
  pool      several variables at once: threads vs a process pool (spawn cost, memory)
  k         Monte-Carlo error of the calibrated p for K = 19, 49, 99

Run:  .venv/Scripts/python scripts/beast_speed.py [--quick] [--only identity,speed] [--diff]
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import math
import os
import statistics
import sys
import time
import types
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.analysis.deseason import deseasonalize  # noqa: E402
from backend.insights import onset  # noqa: E402
from backend.timeseries.model import MonthlySeries, Provenance  # noqa: E402

SRC_PATH = ROOT / "backend" / "insights" / "onset.py"
COMPARED = ("events", "segments", "current_direction_probability", "probability_no_change", "ribbon")

# ------------------------------------------------------------------ candidate patches (old -> new, exact text)
PATCHES: dict[str, list[tuple[str, str]]] = {
    # 1. F-scan: the single-trend fit does not depend on k -> fit it once per scan. Per-k arithmetic unchanged.
    "fscan": [
        ('''def _f_stat(t: np.ndarray, a: np.ndarray, k: int) -> float:
    """F statistic of 'trend + level shift + slope change at k' vs 'single trend' (2 extra params)."""
    ok = np.isfinite(a)
    d = (np.arange(len(a)) >= k).astype(float)
    X1 = np.c_[np.ones(len(a)), t]
    X2 = np.c_[X1, d, d * (t - t[k])]
    y = a[ok]
    r1 = float(np.sum((y - X1[ok] @ np.linalg.lstsq(X1[ok], y, rcond=None)[0]) ** 2))
    r2 = float(np.sum((y - X2[ok] @ np.linalg.lstsq(X2[ok], y, rcond=None)[0]) ** 2))
    dof = int(ok.sum()) - 4
    if r2 <= 0 or dof <= 0:
        return float("inf")
    return (r1 - r2) / 2.0 / (r2 / dof)
''', '''def _f_stats(t: np.ndarray, a: np.ndarray, ks) -> list[float]:
    """F statistic of 'trend + level shift + slope change at k' vs 'single trend' (2 extra params), per k.
    The single-trend fit does not depend on k, so it runs once per scan (same arithmetic, same bits)."""
    ok = np.isfinite(a)
    X1 = np.c_[np.ones(len(a)), t][ok]
    y = a[ok]
    r1 = float(np.sum((y - X1 @ np.linalg.lstsq(X1, y, rcond=None)[0]) ** 2))
    dof = int(ok.sum()) - 4
    idx, tt = np.arange(len(a))[ok], t[ok]
    out = []
    for k in ks:
        d = (idx >= k).astype(float)
        X2 = np.column_stack((X1, d, d * (tt - t[k])))
        r2 = float(np.sum((y - X2 @ np.linalg.lstsq(X2, y, rcond=None)[0]) ** 2))
        out.append(float("inf") if r2 <= 0 or dof <= 0 else (r1 - r2) / 2.0 / (r2 / dof))
    return out


def _f_stat(t: np.ndarray, a: np.ndarray, k: int) -> float:
    return _f_stats(t, a, [k])[0]
'''),
        ("max(_f_stat(t, a, kk) for kk in range(m_lo, max(m_lo + 1, m_hi + 1)))",
         "max(_f_stats(t, a, range(m_lo, max(m_lo + 1, m_hi + 1))))"),
        ("        fs = [(_f_stat(t, a, kk), kk) for kk in cand]\n",
         "        fs = list(zip(_f_stats(t, a, cand), cand))\n"),
    ],
    # 2. Rbeast: same model/prior/MCMC through the documented beast123() interface, minus outputs never read.
    "lean": [
        ('''def _beast_blocks(b: np.ndarray, L: int, start_year: float, seed: int):
    with _quiet_unraisable():
        return _rb.beast(b, start=start_year, deltat=L / 12.0, season="none", quiet=1, print_progress=0,
                         print_options=0, mcmc_seed=seed, tseg_minlen=max(2, 24 // L), tcp_minmax=[0, 5])
''', '''def _beast_blocks(b: np.ndarray, L: int, start_year: float, seed: int, slope: bool = True):
    """The exact model, prior and MCMC settings rb.beast() used here (same posteriors, bit for bit), via
    beast123() so we can skip outputs never read: trend order, change-point lists, input echo and, for the
    surrogates (slope=False), the slope-sign tallies."""
    ns = types.SimpleNamespace
    md = ns(isRegularOrdered=True, season="none", startTime=start_year, deltaTime=L / 12.0, period=float("nan"),
            missingValue=float("nan"), maxMissingRate=0.75, deseasonalize=False, detrend=False,
            hasOutlierCmpnt=False)
    pr = ns(modelPriorType=1, trendMinOrder=0, trendMaxOrder=1, trendMinKnotNum=0, trendMaxKnotNum=5,
            trendMinSepDist=None, trendLeftMargin=None, trendRightMargin=None, K_MAX=0, precValue=1.5,
            precPriorType="componentwise", seasonModelPriorFactor=0.0, trendComplexityFactor=0.0)
    mc = ns(seed=seed, samples=8000, thinningFactor=5, burnin=200, chainNumber=3, maxMoveStepSize=6,
            trendResamplingOrderProb=0.1, seasonResamplingOrderProb=0.17, credIntervalAlphaLevel=0.95)
    ex = ns(dumpInputData=False, whichOutputDimIsTime=1, computeCredible=False, fastCIComputation=True,
            computeSeasonOrder=False, computeTrendOrder=False, computeSeasonChngpt=False, computeTrendChngpt=False,
            computeSeasonAmp=False, computeTrendSlope=slope, tallyPosNegSeasonJump=False, tallyPosNegTrendJump=False,
            tallyIncDecTrendJump=False, printProgress=False, printParameter=False, printWarning=True, quiet=True,
            dumpMCMCSamples=False, consoleWidth=85, numThreadsPerCPU=2, numParThreads=0)
    with _quiet_unraisable():
        return _rb.beast123(np.asarray(b, float), md, pr, mc, ex)
'''),
        ("    o = _beast_blocks(_blocks(a, L), L, start_year, seed)\n",
         "    o = _beast_blocks(_blocks(a, L), L, start_year, seed, slope=False)\n"),
        ("import sys\n", "import sys\nimport types\n"),
    ],
    # 3. Surrogates in worker processes. Surrogate series are drawn first, in the same order, so rng use is unchanged.
    "pool": [
        ("import sys\n", "import os\nimport sys\nfrom concurrent.futures import ProcessPoolExecutor\n"
                         "from concurrent.futures.process import BrokenProcessPool\n"),
        ('''# ------------------------------------------------------------------ main
''', '''_POOL: ProcessPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def _surrogate_pool() -> ProcessPoolExecutor:
    """Worker processes for the surrogate BEAST runs (Rbeast holds the GIL, so threads cannot run them in parallel)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ProcessPoolExecutor(max_workers=max(1, min(6, (os.cpu_count() or 2) - 1)))
        return _POOL


# ------------------------------------------------------------------ main
'''),
        ('''    null = []
    for i in range(int(n_surrogates)):
        s = slope * t + icpt + _ar1(phi, n, rng) * sig
        s[miss] = np.nan
        null.append(_top_change_stat(t, s, L, start_year, seed + 1 + i, edge))
''', '''    sur = []
    for i in range(int(n_surrogates)):
        s = slope * t + icpt + _ar1(phi, n, rng) * sig
        s[miss] = np.nan
        sur.append(s)
    K, seeds = len(sur), [seed + 1 + i for i in range(len(sur))]
    try:
        null = list(_surrogate_pool().map(_top_change_stat, [t] * K, sur, [L] * K, [start_year] * K, seeds,
                                          [edge] * K, chunksize=max(1, K // 24)))
    except BrokenProcessPool:  # a worker died: same numbers, computed here
        null = [_top_change_stat(t, s, L, start_year, sd_, edge) for s, sd_ in zip(sur, seeds)]
'''),
    ],
}


def patched_source(names: tuple[str, ...]) -> str:
    src = SRC_PATH.read_text(encoding="utf-8")
    for name in names:
        for old, new in PATCHES[name]:
            assert src.count(old) == 1, f"patch {name}: anchor not found exactly once: {old[:60]!r}"
            src = src.replace(old, new)
    return src


def load_variant(names: tuple[str, ...]) -> types.ModuleType:
    """Import a patched copy of onset.py as backend.insights._onset_<names> (also used as a pool initializer)."""
    modname = "backend.insights._onset_" + "_".join(names)
    if modname in sys.modules:
        return sys.modules[modname]
    mod = types.ModuleType(modname)
    mod.__package__ = "backend.insights"
    mod.__file__ = str(SRC_PATH)
    sys.modules[modname] = mod
    exec(compile(patched_source(names), f"<onset+{'+'.join(names)}>", "exec"), mod.__dict__)
    return mod


def variant(names: tuple[str, ...], workers: int = 6) -> types.ModuleType:
    mod = load_variant(names)
    if "pool" in names and mod._POOL is None:  # workers must import the same in-memory variant
        mod._POOL = ProcessPoolExecutor(workers, initializer=load_variant, initargs=(names,))
    return mod


def print_diffs() -> None:
    base = SRC_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    for name in PATCHES:
        new = patched_source((name,)).splitlines(keepends=True)
        sys.stdout.writelines(difflib.unified_diff(base, new, "a/backend/insights/onset.py",
                                                   "b/backend/insights/onset.py", n=2))
        print()


# ------------------------------------------------------------------ test series
def make_series(n: int, seed: int, phi: float = 0.5, change: float = 0.0, missing: str = "none") -> MonthlySeries:
    rng = np.random.default_rng(seed)
    t = np.arange(n) / 12
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = phi * e[i - 1] + rng.normal()
    tc = t[n // 2]
    y = 2 * np.sin(2 * np.pi * t) + 0.02 * t + 0.4 * e + np.where(t >= tc, change * (0.5 + 0.1 * (t - tc)), 0)
    if missing == "random":
        y[rng.random(n) < 0.06] = np.nan
    elif missing == "gap":
        g = int(rng.integers(30, n - 50))
        y[g:g + 14] = np.nan
    elif missing == "lead":
        y[:18] = np.nan
        y[rng.random(n) < 0.03] = np.nan
    idx = pd.date_range("1995-01-01", periods=n, freq="MS")
    return MonthlySeries(idx, y, "x", Provenance("synthetic", "x", {}))


def identity_set(count: int, K: int) -> tuple[list[MonthlySeries], list[dict]]:
    """`count` varied series on which the current code returns status 'ok', plus their baseline results."""
    lengths, phis = (120, 288, 528, 200, 360), (0.0, 0.3, 0.5, 0.7, 0.85, 0.6)
    miss, chg = ("none", "random", "gap", "lead"), (0.0, 0.6, 1.5)
    sers, base, i = [], [], 0
    while len(sers) < count:
        ms = make_series(lengths[i % 5], 1000 + i, phis[i % 6], chg[i % 3], miss[i % 4])
        r = onset.change_onset(ms, n_surrogates=K)
        i += 1
        if r["status"] == "ok":
            sers.append(ms)
            base.append(r)
    return sers, base


def canon(res: dict, keys=COMPARED) -> str:
    return json.dumps({k: res.get(k) for k in keys}, sort_keys=True)


# ------------------------------------------------------------------ 1. profile
@contextlib.contextmanager
def instrumented(acc: dict):
    """Wrap onset internals with timers; first BEAST call in a change_onset is the real series."""
    orig = {k: getattr(onset, k) for k in ("_beast_blocks", "_f_stat", "_ar1", "deseasonalize", "_top_change_stat")}
    state = {"in_sur": False, "beast_calls": 0}

    def timed(key_fn, fn):
        def w(*a, **k):
            t0 = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                key = key_fn()
                acc[key] = acc.get(key, 0.0) + time.perf_counter() - t0
        return w

    def beast_key():
        state["beast_calls"] += 1
        return "BEAST surrogates" if state["in_sur"] else "BEAST real series"

    def top(*a, **k):
        state["in_sur"] = True
        try:
            return orig["_top_change_stat"](*a, **k)
        finally:
            state["in_sur"] = False

    onset._beast_blocks = timed(beast_key, orig["_beast_blocks"])
    onset._f_stat = timed(lambda: "F-scan surrogates" if state["in_sur"] else "F-scan real series", orig["_f_stat"])
    onset._ar1 = timed(lambda: "AR(1) surrogate draws", orig["_ar1"])
    onset.deseasonalize = timed(lambda: "deseasonalize", orig["deseasonalize"])
    onset._top_change_stat = top
    try:
        yield
    finally:
        for k, v in orig.items():
            setattr(onset, k, v)


def profile(quick: bool) -> None:
    reps = 1 if quick else 3
    print("\n## Profile: one change_onset call (phi 0.5 -> block 3 months), median of", reps)
    onset.change_onset(make_series(120, 1), n_surrogates=2)  # warm-up (imports, Rbeast load)
    rows = [(n, 49) for n in (120, 288, 528)] + [(288, 19), (288, 99)]
    print("| months | K | wall s | BEAST real | BEAST surrogates | F-scan real | F-scan surrogates | AR(1) draws | "
          "deseasonalize | other Python/numpy |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for n, K in rows:
        ms = make_series(n, 7, phi=0.5, change=1.0)
        walls, accs = [], []
        for _ in range(reps):
            acc: dict = {}
            with instrumented(acc):
                t0 = time.perf_counter()
                onset.change_onset(ms, n_surrogates=K)
                walls.append(time.perf_counter() - t0)
            accs.append(acc)
        i = int(np.argsort(walls)[len(walls) // 2])
        wall, acc = walls[i], accs[i]
        keys = ("BEAST real series", "BEAST surrogates", "F-scan real series", "F-scan surrogates",
                "AR(1) surrogate draws", "deseasonalize")
        other = wall - sum(acc.get(k, 0.0) for k in keys)
        cells = [f"{acc.get(k, 0.0):.3f} ({acc.get(k, 0.0) / wall:.0%})" for k in keys]
        print(f"| {n} | {K} | {wall:.2f} | " + " | ".join(cells) + f" | {other:.3f} ({other / wall:.0%}) |")


# ------------------------------------------------------------------ 2. identity + 3. speed
CANDIDATES = (("fscan",), ("lean",), ("pool",), ("fscan", "lean"), ("fscan", "lean", "pool"))


def identity(quick: bool) -> None:
    K = 9 if quick else 49
    sers, base = identity_set(20 if quick else 24, K)
    print(f"\n## Identity: {len(sers)} series (lengths 120-528, phi 0-0.85, 4 missing-month patterns), K = {K}")
    n_ev = sum(len(b["events"]) for b in base)
    n_conf = sum(e["status"] == "confirmed" for b in base for e in b["events"])
    print(f"(baseline: {n_ev} events, {n_conf} confirmed, block lengths "
          f"{sorted({b['memory']['block_months'] for b in base})})")
    print("| candidate | series with identical events/segments/direction/p_no_change/ribbon | whole result identical |")
    print("|---|---|---|")
    for names in CANDIDATES:
        mod = variant(names)
        got = [mod.change_onset(s, n_surrogates=K) for s in sers]
        same5 = sum(canon(a) == canon(b) for a, b in zip(base, got))
        same_all = sum(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) for a, b in zip(base, got))
        print(f"| {'+'.join(names)} | {same5}/{len(sers)} | {same_all}/{len(sers)} |")


def other_pythons() -> int:
    """Other python.exe processes on the machine (shared laptop: timings are only clean when this is ~0)."""
    if os.name != "nt":
        return -1
    out = os.popen('tasklist /FI "IMAGENAME eq python.exe" /NH').read()
    own = 2 if sys.prefix != sys.base_prefix else 1  # a venv python.exe is a launcher plus the real interpreter
    return max(0, out.lower().count("python.exe") - own - len(multiprocessing_children()))


def multiprocessing_children() -> list:
    import multiprocessing
    return multiprocessing.active_children()


def speed(quick: bool) -> None:
    reps = 2 if quick else 5
    ms = make_series(288, 7, phi=0.5, change=1.0, missing="random")
    print(f"\n## Speed: one call, 288 months, K = 49, median of {reps} interleaved rounds (pools warm); "
          f"other python processes running: {other_pythons()}")
    print("| candidate | median wall s | wall speed-up | median CPU s in calling process | CPU speed-up |")
    print("|---|---|---|---|---|")
    labels = (("baseline",),) + CANDIDATES
    mods = [onset if names == ("baseline",) else variant(names) for names in labels]
    for mod in mods:
        mod.change_onset(ms, n_surrogates=12)  # warm-up (starts pool workers)
    wall = {i: [] for i in range(len(mods))}
    cpu = {i: [] for i in range(len(mods))}
    for _ in range(reps):  # interleaved, so background load hits every candidate alike
        for i, mod in enumerate(mods):
            t0, c0 = time.perf_counter(), time.process_time()
            mod.change_onset(ms)
            wall[i].append(time.perf_counter() - t0)
            cpu[i].append(time.process_time() - c0)
    w0, c0 = statistics.median(wall[0]), statistics.median(cpu[0])
    for i, names in enumerate(labels):
        w, c = statistics.median(wall[i]), statistics.median(cpu[i])
        cs = f"{c0 / c:.2f}x" if "pool" not in names else "n/a (work moved to workers)"
        print(f"| {'+'.join(names)} | {w:.2f} | {w0 / w:.2f}x | {c:.2f} | {cs} |")
    if not quick:
        print("\nPool size sweep (fscan+lean+pool, warm):")
        for w in (2, 4, 6, 8, 11):
            names = ("fscan", "lean", "pool")
            mod = load_variant(names)
            if mod._POOL is not None:
                mod._POOL.shutdown()
            mod._POOL = ProcessPoolExecutor(w, initializer=load_variant, initargs=(names,))
            mod.change_onset(ms, n_surrogates=2 * w)
            ts = []
            for _ in range(3):
                t0 = time.perf_counter()
                mod.change_onset(ms)
                ts.append(time.perf_counter() - t0)
            print(f"  workers={w:2d}: {statistics.median(ts):.2f} s")


# ------------------------------------------------------------------ 4. several variables: threads vs processes
def rss_mb(pid: int | None = None) -> float | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes as w

    class PMC(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [(f, ctypes.c_size_t) for f in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.OpenProcess.restype = k32.GetCurrentProcess.restype = w.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(PMC), w.DWORD]
    h = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(0x0410, False, pid)
    c = PMC()
    c.cb = ctypes.sizeof(c)
    ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
    if pid is not None:
        k32.CloseHandle(h)
    return c.WorkingSetSize / 2 ** 20 if ok else None


def _import_only(_=None) -> int:
    from backend.insights import onset as _  # noqa: F401  (what a worker must load)
    return os.getpid()


def pool(quick: bool) -> None:
    V = 4
    sers = [make_series(288, 50 + i, phi=(0.3, 0.5, 0.6, 0.4)[i % 4], change=(0, 1, 0.5, 1.5)[i % 4]) for i in range(V)]
    print(f"\n## Several variables at once: {V} series of 288 months, K = 49")
    onset.change_onset(sers[0], n_surrogates=2)

    def run(label, fn):
        t0 = time.perf_counter()
        out = fn()
        dt = time.perf_counter() - t0
        print(f"| {label} | {dt:.2f} |")
        return out

    print("| how | wall s |")
    print("|---|---|")
    ref = run("serial (current code, one after another)", lambda: [onset.change_onset(s) for s in sers])
    with ThreadPoolExecutor(V) as ex:
        thr = run(f"threads x{V} (what runner.py does today)", lambda: list(ex.map(onset.change_onset, sers)))
    t0 = time.perf_counter()
    pp = ProcessPoolExecutor(V)
    list(pp.map(_import_only, range(V * 3)))
    spawn = time.perf_counter() - t0
    print(f"| process pool x{V}: start {V} workers + import backend (cold) | {spawn:.2f} |")
    prc = run(f"process pool x{V}, one variable per worker (warm)", lambda: list(pp.map(onset.change_onset, sers)))
    mems = [rss_mb(p) for p in pp._processes] if os.name == "nt" else []
    pp.shutdown()
    t0 = time.perf_counter()
    with ProcessPoolExecutor(V) as pp2:
        list(pp2.map(onset.change_onset, sers))
    print(f"| process pool x{V}, cold (spawn + run + shutdown) | {time.perf_counter() - t0:.2f} |")
    names = ("fscan", "lean", "pool")
    mod = variant(names)
    mod.change_onset(sers[0], n_surrogates=12)
    with ThreadPoolExecutor(V) as ex:
        sp = run("threads x4 + surrogate pool x6 (patches 1+2+3, warm)", lambda: list(ex.map(mod.change_onset, sers)))
    same = all(canon(a) == canon(b) for a, b in zip(ref, thr)) and all(canon(a) == canon(b) for a, b in zip(ref, prc)) \
        and all(canon(a) == canon(b) for a, b in zip(ref, sp))
    print(f"\nall four ways give identical results: {same}")
    if mems:
        print(f"memory: parent working set {rss_mb():.0f} MB; each worker after one call "
              f"{', '.join(f'{m:.0f}' for m in mems if m)} MB")


# ------------------------------------------------------------------ 5. K trade-off
def null_stats(ms: MonthlySeries, K: int, seed: int, ex: ProcessPoolExecutor) -> np.ndarray:
    """The same null as change_onset (same rng stream and MCMC seeds), extended to K surrogates."""
    a = deseasonalize(ms, "climatology").deseasonalized
    t = ms.t_years()
    n = len(a)
    start_year = ms.time[0].year + (ms.time[0].month - 1) / 12.0
    slope, icpt, phi, sd = onset._line_and_memory(t, a)
    L = onset.block_length(phi)
    edge = 24 if n >= 96 else max(12, n // 4)
    rng = np.random.default_rng(seed)
    sig = sd * math.sqrt(max(1 - phi * phi, 1e-6))
    miss = ~np.isfinite(a)
    sur = []
    for _ in range(K):
        s = slope * t + icpt + onset._ar1(phi, n, rng) * sig
        s[miss] = np.nan
        sur.append(s)
    return np.asarray(list(ex.map(onset._top_change_stat, [t] * K, sur, [L] * K, [start_year] * K,
                                  [seed + 1 + i for i in range(K)], [edge] * K, chunksize=8)))


def k_tradeoff(quick: bool) -> None:
    from scipy.stats import binom
    alpha = 0.05
    print("\n## K trade-off. Exact: P(confirmed) when the true calibrated p is p0, p_hat = (1 + X)/(K + 1), "
          "X ~ Binomial(K, p0), confirm if p_hat < 0.05")
    print("| true p0 | K=19 | K=49 | K=99 | K=199 |")
    print("|---|---|---|---|---|")
    for p0 in (0.001, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10):
        cells = []
        for K in (19, 49, 99, 199):
            xmax = math.ceil(alpha * (K + 1) - 1) - 1  # largest X with (1+X)/(K+1) < alpha
            cells.append(f"{binom.cdf(xmax, K, p0):.2f}" if xmax >= 0 else "0 (impossible)")
        print(f"| {p0} | " + " | ".join(cells) + " |")
    print("Smallest p each K can report: " + ", ".join(f"K={K}: {1 / (K + 1):.3f}" for K in (19, 49, 99, 199)))

    Kref = 99 if quick else 495
    cases = [(0.3, 0.0), (0.3, 0.5), (0.3, 1.0), (0.6, 0.0), (0.6, 1.0), (0.6, 2.0), (0.45, 0.7), (0.45, 1.5)]
    if quick:
        cases = cases[:3]
    print(f"\nEmpirical: same series, observed F fixed; null of {Kref} surrogates split into disjoint chunks of K")
    print("| phi | change | F | p (K=49, as returned) | p_ref (K=" + str(Kref) + ") | K=19 mean / sd / flip | "
          "K=49 mean / sd / flip | K=99 mean / sd / flip |")
    print("|---|---|---|---|---|---|---|---|")
    with ProcessPoolExecutor(max(1, min(6, (os.cpu_count() or 2) - 1))) as ex:
        for j, (phi, chg) in enumerate(cases):
            ms = make_series(288, 300 + j, phi=phi, change=chg)
            res = onset.change_onset(ms)
            if not res["events"]:
                print(f"| {phi} | {chg} | - | no event | | | | |")
                continue
            F, p49 = res["events"][0]["f_stat"], res["events"][0]["p_calibrated"]
            null = null_stats(ms, Kref, 2026, ex)
            assert (1 + np.sum(null[:49] >= F)) / 50 == p49, "null reproduction differs from change_onset"
            p_ref = (1 + np.sum(null >= F)) / (Kref + 1)
            cells = []
            for K in (19, 49, 99):
                ps = np.array([(1 + np.sum(null[i:i + K] >= F)) / (K + 1) for i in range(0, Kref - K + 1, K)])
                flip = np.mean((ps < alpha) != (p_ref < alpha))
                cells.append(f"{ps.mean():.3f} / {ps.std(ddof=1):.3f} / {flip:.0%} (n={len(ps)})")
            print(f"| {phi} | {chg} | {F:.1f} | {p49:.3f} | {p_ref:.3f} | " + " | ".join(cells) + " |")


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="fewer series, repeats and surrogates (~2-3 min)")
    ap.add_argument("--only", default="profile,identity,speed,pool,k")
    ap.add_argument("--diff", action="store_true", help="print the candidate patches as unified diffs and exit")
    args = ap.parse_args()
    if args.diff:
        print_diffs()
        return
    if not onset.available():
        sys.exit("Rbeast is not installed")
    import hashlib
    sha = hashlib.sha256(SRC_PATH.read_bytes()).hexdigest()[:12]
    print(f"Python {sys.version.split()[0]}, numpy {np.__version__}, {os.cpu_count()} logical CPUs; "
          f"onset.py sha256 {sha} (modified {time.ctime(SRC_PATH.stat().st_mtime)})")
    steps = {"profile": profile, "identity": identity, "speed": speed, "pool": pool, "k": k_tradeoff}
    for name in args.only.split(","):
        t0, busy = time.perf_counter(), other_pythons()
        steps[name.strip()](args.quick)
        print(f"({name} took {time.perf_counter() - t0:.0f} s; other python processes at start: {busy}, "
              f"at end: {other_pythons()})")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
