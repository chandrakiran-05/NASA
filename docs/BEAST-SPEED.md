# BEAST change-onset: where the time goes and how to make it faster

Scope: `change_onset()` in `backend/insights/onset.py`. Everything here was measured with
`scripts/beast_speed.py` on the team laptop (6 cores / 12 threads, 16 GB RAM, Windows 11, Python 3.12,
numpy 2.5, Rbeast 0.1.25). Nothing in `backend/` was changed; the patches below are proposals.

## Summary in plain English

- **Almost all the time is BEAST itself, and almost all of that is the surrogates.** One call at 288 months
  runs BEAST 50 times (1 real series + 49 simulated "no change" series). The 49 surrogate runs take about
  88-90 % of the time, the real-series run 2-5 %, the month-by-month F-test scans about 8 %, everything
  else about 1 %.
- **Series length hardly matters; K matters linearly.** BEAST's cost is fixed by its MCMC settings
  (3 chains x 40 200 iterations), not by the number of months, so 120, 288 and 528 months cost about the
  same. Doubling K doubles the time.
- **Three safe speed-ups, all proven to give bit-identical results** (24 random series, with missing
  months, K = 49, every field of the result compared as exact JSON):
  1. *F-scan*: fit the "single trend" model once per scan instead of once per candidate month: ~1.1x.
  2. *Lean BEAST*: same BEAST model through Rbeast's documented `beast123()` interface, but switch off
     outputs we never read: ~1.1x.
  3. *Surrogate process pool*: run the 49 surrogate BEAST runs in worker processes: **~2.3x** (warm pool,
     machine busy with another job during the measurement; see the note below the speed table).
  All three together: see the speed table.
- **Threads cannot help; processes can.** Rbeast keeps Python's GIL while it runs, so several variables in
  threads take as long as running them one after another. A process pool does run them in parallel. Pooling
  the *surrogates* (patch 3) is better than pooling whole variables: it also speeds up a single
  `/onset` request and needs no change in `runner.py`.
- **K = 49 is a reasonable default, but its p-value is coarse.** With K = 49 the smallest possible p is
  0.02 and a change is "confirmed" only if at most 1 of 49 surrogates beats it. For a borderline change
  (true p between 0.02 and 0.05) the confirm / not-confirm decision is close to a coin flip at every
  K up to 199. K = 99 halves the Monte-Carlo noise for twice the time. **K = 19 can never confirm
  anything at alpha = 0.05** (its smallest p is exactly 0.05 and the rule is p < 0.05).
- **Two bugs found** (details at the end):
  1. `tseg_minlen=...` is not an Rbeast argument and is silently ignored, so BEAST allows trend changes
     only a few months apart, contrary to the intended 24-month minimum.
  2. `GET /api/analyze/{id}/onset?n_surrogates=19` (allowed by the route) can never return "confirmed";
     the same happens for any K < 1/alpha - 1 (e.g. alpha = 0.01 with the default K = 49).

## 1. Where the time goes

PLACEHOLDER_PROFILE

Notes: "BEAST" is the Rbeast C call (`cbeast.Rbeast`); per call it costs ~45-95 ms depending on load,
almost independent of the number of blocks. "F-scan" is `_f_stat` (two `np.linalg.lstsq` per candidate
month, ~30 candidate months per series). AR(1) draws, deseasonalising, `_blocks`, segments and the ribbon
are each well under 1 %.

## 2. Safe speed-ups (identical results for a fixed seed)

Identity proof (`scripts/beast_speed.py --only identity`): 24 series that the current code accepts
(lengths 120-528 months, lag-1 autocorrelation 0-0.85 so block lengths 1-12, no change / small / large
change, four missing-month patterns: none, ~6 % random, a 14-month gap, 18 leading months missing plus
~3 % random), K = 49. For each candidate the whole result dictionary was compared with the current code
as exact JSON (floats compared by their exact repr), not only `events`, `segments`,
`current_direction_probability`, `probability_no_change` and `ribbon`.

PLACEHOLDER_IDENTITY

PLACEHOLDER_SPEED

What was checked and rejected:

- **Vectorising the F-scan** (one batched least-squares for all candidate months, or normal equations,
  or rank-one updates) is faster in pure numpy but does not give the same last bits as `lstsq`, so
  `f_stat` and potentially `p_calibrated` ties could change. Not proposed; the bit-identical version
  already removes half the work, and the scan is only ~8 % of the time.
- **Cheaper Rbeast options that are output-neutral**: `computeTrendOrder`, `computeSeasonOrder`,
  `computeTrendChngpt`, `computeSeasonChngpt`, `dumpInputData` and (surrogates only) `computeTrendSlope`
  only switch off *summaries* of the chain; they do not touch the random-number stream. Verified bit for
  bit on every posterior field we read (`cpOccPr`, `ncpPr`, `slpSgnPosPr`, `slpSgnZeroPr`, `Y`).
  `computeCredible` is already off. `mcmc_samples`, `mcmc_burnin`, chains and thinning were not changed.
  Rbeast's own thread settings (`numThreadsPerCPU`, `numParThreads`) do not change a single-series run.
- **One multi-series BEAST call for all surrogates** (`beast123` with a 2-D input and `numParThreads`
  = K) runs the surrogates on C threads without the GIL (12 series: 1.29 s one by one vs 0.24 s in
  one call, measured while the machine was busy). It is **not** bit-identical: Rbeast seeds its random
  generator once per C thread, not once per series, so every surrogate would get MCMC seed `seed`
  instead of `seed + 1 + i` (measured: with T threads exactly the first T columns equal a single run with
that seed; later columns continue a thread's random stream, so they depend on how series are assigned to
threads).
  Statistically harmless, but it changes p values for a fixed seed and would need the calibration study
  re-run. Not proposed here.

### Patch 1: F-scan, single-trend fit once per scan

Proof: identical on 24/24 series (whole result). Why it is exact: `r1` (the single-trend residual sum of
squares) never depended on `k`; the same `lstsq` on the same array is now done once instead of ~30
times. The two-break design matrix holds the same numbers (rows selected before instead of after
stacking), and `max` over the same sequence is unchanged, including the tie rule of `max(fs)`.

```diff
PLACEHOLDER_DIFF_FSCAN
```

### Patch 2: lean BEAST call

Proof: identical on 24/24 series (whole result); additionally every posterior field identical on direct
Rbeast calls. The settings are exactly what `Rbeast.beast()` builds internally (copied from
`Rbeast/beast.py`, v0.1.25) with `trendMinSepDist=None` kept on purpose, because that is what the current
code effectively passes (see bug 1). Risk: it hard-codes Rbeast's internal defaults, so a future Rbeast
upgrade must re-run `scripts/beast_speed.py --only identity`.

```diff
PLACEHOLDER_DIFF_LEAN
```

### Patch 3: surrogates in a process pool

Proof: identical on 24/24 series (whole result). Why it is exact: every surrogate series is still drawn
from the same `rng` in the same order before any BEAST run (BEAST never touches `rng`), every surrogate
keeps its own MCMC seed `seed + 1 + i`, and `map` returns results in input order. If a worker dies the
same numbers are computed in-process.

```diff
PLACEHOLDER_DIFF_POOL
```

## 3. Several variables at once: threads vs processes

PLACEHOLDER_POOL

Is a process pool safe with the module-level state?

- `_HOOK_LOCK` and the `sys.unraisablehook` swap are per process. Each worker has its own copy, nothing
  is shared, nothing needs pickling (only the module-level function `_top_change_stat` and numpy arrays
  cross the process boundary).
- The worker only imports `backend.insights.onset` (numpy, pandas, Rbeast, the analysis helpers). It
  never touches the app state, the SQLite cache or the job queue.
- Windows uses *spawn*: a worker re-imports the program's main module. Under `uvicorn backend.main:app`
  and pytest that is safe (guarded entry points). A script that calls `change_onset` must keep its code
  under `if __name__ == "__main__":` (all scripts in `scripts/` already do).
- The pool is created lazily on the first call and reused; `concurrent.futures` shuts it down at
  interpreter exit. The `_POOL_LOCK` makes concurrent first calls from the runner's threads safe, and
  `ProcessPoolExecutor.map` itself is thread-safe, so the runner can keep running variables in threads.
- Per-variable pooling (submitting whole `change_onset` calls) would need the runner to pass picklable
  arguments instead of the current lambda, and caps parallelism at the number of variables; the
  surrogate pool needs neither.
- With 6 workers BEAST uses 6 of 12 logical CPUs; the API stays responsive. Do not size it above
  the physical core count (see the pool-size sweep).

## 4. Is K = 49 a good trade-off?

The calibrated p is `(1 + #surrogates with F >= observed F) / (K + 1)`, so it is a Monte-Carlo estimate
with binomial noise, and its smallest value is `1 / (K + 1)`.

PLACEHOLDER_K

How to read it:

- Clear changes (true p well below 0.02) are confirmed at K = 49 almost always; clear non-changes
  (p > 0.1) almost never. K only matters for borderline cases.
- At K = 49 the rule p < 0.05 means "at most 1 of 49 surrogates is as strong", i.e. an effective
  threshold of p <= 0.04. A change with true p = 0.03 is confirmed 57 % of the time at K = 49, 65 % at
  K = 99. No practical K makes borderline cases stable; the honest fix is to report p with its
  Monte-Carlo uncertainty (+/- sqrt(p(1-p)/K)), not to raise K.
- With patch 3, K = 99 at 288 months costs about what K = 49 costs today. That is the cheapest way to
  halve the Monte-Carlo noise if the team wants it. The default was not changed.
- **K = 19 is not usable at alpha = 0.05**: its p can never be below 0.05 (column "K=19 flip" is 100 %
  for every confirmed series). `tests/test_active.py` uses K = 19, which is fine there (it only checks the
  direction gate) but the route allows it for users.

## 5. Bugs found

### Bug 1: the 24-month minimum segment length is silently ignored

`_beast_blocks` passes `tseg_minlen=max(2, 24 // L)`. Rbeast's argument is `tseg_minlength`;
`beast()` swallows unknown keywords in `**kwargs` and only reads `freq`, `ci`, `cputype` and `local`
from them. Concrete case (`L = 1`, 288 months, `seed = 0`, noise + a level shift at 2011 and back at
2012): the output with `tseg_minlen=24` is bit-identical to the output with no argument at all, differs
from `tseg_minlength=24`, and its change points are 6 months apart (2012.0 and 2012.5). Seeds 1 and 2
give gaps of 7 and 4 months. (`print_options=0` is ignored the same way, harmlessly, because
`quiet=1`.)

Smallest fix (changes results, so re-run `scripts/onset_calibration.py` and update the table in the
module docstring afterwards):

```diff
-                         print_options=0, mcmc_seed=seed, tseg_minlen=max(2, 24 // L), tcp_minmax=[0, 5])
+                         mcmc_seed=seed, tseg_minlength=max(2, 24 // L), tcp_minmax=[0, 5])
```

(If patch 2 is applied, set `trendMinSepDist=max(2, 24 // L)` there instead of `None`.)

### Bug 2: some K / alpha combinations can never confirm a change

`p_calibrated >= 1 / (K + 1)`, and the rule is `p_calibrated < alpha`. The route accepts
`n_surrogates` from 19 and `alpha` up to 0.5 down to any positive value, so `n_surrogates=19, alpha=0.05`
or the default `n_surrogates=49` with `alpha=0.01` always return "possible" at best, while the text says
the change "is not stronger than what persistent noise produces". Smallest fix, in `change_onset`, just
before the surrogate loop:

```diff
+    n_surrogates = max(int(n_surrogates), math.ceil(1 / alpha))  # otherwise p < alpha is impossible
```

(It only changes calls that could not confirm anything; `n_surrogates` in the result reports the K
actually used.)

## How to reproduce

```
.venv/Scripts/python scripts/beast_speed.py --quick     # ~5 min, 20 series, K = 9 for identity
.venv/Scripts/python scripts/beast_speed.py             # full run, ~15 min
.venv/Scripts/python scripts/beast_speed.py --diff      # print the three patches
```
