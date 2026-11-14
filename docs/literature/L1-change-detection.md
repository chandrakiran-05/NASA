# L1: Advanced trend and change-point methods (agent report)

**How the sources were checked**
- Citations were confirmed through publisher, repository or Crossref metadata. The full texts were **not** opened.
- Packages were checked on PyPI, GitHub and rdrr.io.
- Run times are estimates.

## 1. BEAST (Bayesian ensemble of trend + season + change points)
- **Method:** fits thousands of trend and season models, each with different breakpoints, and averages them. Every output therefore comes with a probability.
- **Papers:**
  - Zhao, Wulder, Hu et al. 2019, *RSE* 232:111181, doi:10.1016/j.rse.2019.04.034.
  - Di Nunno, de Marinis & Granata 2024, *J. Hydrol. Reg. Stud.* 52:101717, doi:10.1016/j.ejrh.2024.101717. BEAST caught abrupt wet-to-dry shifts that seasonal MK missed.
- **Code:** `pip install rbeast` (v0.1.25, Apr 2026, MIT). Wheels are available for Python 3.7–3.14 on macOS, Linux and Windows. Call it as `rb.beast(y, start=2001, deltat=1/12, period=1.0)`.
- **New outputs:**

  | Field | What it gives |
  |---|---|
  | `trend.cpOccPr` | Probability of a change point in each month |
  | `cp`, `cpPr`, `cpCI` | Change date, its probability, and a credible interval |
  | `slpSgnPosPr`, `slpSgnZeroPr` | Probability that the trend is rising or flat in each month |
  | `ncpPr` | Distribution of the number of change points |
  | `pos_`, `neg_`, `inc_`, `dec_` fields | Breakdown into jumps up or down and slope increases or decreases |
  | Seasonal change points | e.g. a shift in NDVI green-up |
- **Fit:** all of our datasets, and best for seasonal ones (MODIS, IMERG, GLDAS, SMAP).
- **Feasibility:** High. Under 1 s per series.

## 2. Segmented regression with a breakpoint CI
- **Method:** fits a straight-line trend in pieces and estimates where the slope changes.
- **Paper:** Pilgrim 2021, *JOSS* 6(68):3859, doi:10.21105/joss.03859 (Muggeo's method).
- **Code:** `pip install piecewise-regression` (v1.5.0, MIT).
- **Outputs:** break date ± CI (e.g. "2012 ± 1.3 yr"), slope before and after with p-values, a Davies test, and BIC to choose how many breakpoints.
- **Feasibility:** High, runs in milliseconds. Run it on the STL anomalies.

## 3. Time of Emergence + years-to-detect
- **Papers:**
  - Hawkins & Sutton 2012, *GRL* 39:L01702, doi:10.1029/2011GL050087.
  - Hawkins et al. 2020, *GRL* 47:e2019GL086259, doi:10.1029/2019GL086259 (the observations-based version).
  - Weatherhead et al. 1998, *JGR* 103(D14):17149–17161, doi:10.1029/98JD00995. DOI confirmed via Crossref. The formula n* ≈ [3.3σ_N/|ω|·√((1+φ)/(1−φ))]^(2/3) still needs checking against the paper itself.
- **Code:** about 20 lines of NumPy.
- **Outputs:**
  - The signal-to-noise (S/N) ratio.
  - The year the trend emerged from the noise, or "not yet emerged".
  - "You need N more years."
- **Feasibility:** High, negligible run time.

## 4. Dynamic linear model (time-varying trend)
- **Method:** lets the trend slope change smoothly over time, with a credible band.
- **Papers:**
  - Laine et al. 2014, *ACP* 14:9707.
  - Alsing 2019, *JOSS* 4(37):1157, doi:10.21105/joss.01157.
- **Code:** github.com/justinalsing/dlmmc (MIT, Stan/PyStan).
- **Outputs:** a smooth trend with a credible band, plus ENSO and solar regressors.
- **Feasibility:** Medium-Low, because Stan has install risk.

## 5. ruptures (PELT etc.)
- **Paper:** Truong, Oudre & Vayatis 2020, *Signal Processing* 167:107299, arXiv:1801.00718.
- **Code:** `pip install ruptures` (v1.1.10, BSD-2).
- **Outputs:** dates where the mean or variance shifts. A variance shift can flag a sensor or algorithm change, which links to F1.
- **Feasibility:** High, runs in milliseconds.

## 6. BFAST Lite / CCDC: low fit
- **Paper:** Masiliūnas et al. 2021, *Remote Sensing* 13:3308, doi:10.3390/rs13163308.
- **BFAST Lite:** only available in R. The Python `bfast` package only covers BFASTmonitor and needs OpenCL.
- **CCDC** (`lcmap-pyccd`): built for per-pixel Landsat analysis.
- BEAST covers the same ground.

## Agent's top 2
1. **BEAST "Change Detective":** probabilities in place of a yes/no answer, plus seasonal change points. Qwen narrates the probability curves.
2. **Time of Emergence + years-to-detect.**

Segmented regression and ruptures serve as cross-checks for "agreement across 3 methods".
