# R2: Advanced spatial trend features

All citations and libraries below were checked. Per-pixel BEAST was tested on a synthetic 40×40×300 cube.

## 1. Cluster-size permutation field significance (BH-FDR fallback)

**Problem.** Single pixels that pass p < 0.05 are often false alarms. Real trends form large connected patches, while false positives form small, scattered ones.

**Evidence.** Cortés et al. 2021 (GRL 48:e2020GL091496, doi:10.1029/2020GL091496; full text read) used this correction and the share of global land showing significant greening fell from 35.2% to 15.3%. See also Wilks 2016 (BAMS 97:2263, doi:10.1175/BAMS-D-15-00267.1, paywalled). The "q = 0.10" rule of thumb is from secondary sources only.

**Algorithm.**
1. Run Mann-Kendall plus Sen's slope on every pixel.
2. Label 8-connected clusters of significant pixels, separately for positive and negative slopes (`scipy.ndimage.label`).
3. Permute time jointly across all pixels, using 12–24-month blocks on deseasonalized data so the autocorrelation is kept.
4. Record the largest cluster from each permutation.
5. Keep observed clusters larger than the (1−α) quantile of those maxima.

**Fallback.** `multipletests(method='fdr_bh')` at q = 0.10.

**Compute.** About 0.5 s per monthly permutation, so about 8 minutes for 1,000. To make it faster, use annual means or a t-statistic.

## 2. "Hidden by averaging" panel

**Evidence.** Pan et al. 2018 (RSE 214:59, doi:10.1016/j.rse.2018.05.018; abstract only): browning was hidden inside overall greening.

**Outputs** (all cos(lat)-weighted):
- % of area significantly rising and % significantly falling.
- The slope of the regional mean.
- Cancellation index = 1 − |Σw·b| / Σw·|b|. This is our own metric, not from the literature.
- Representativeness = median correlation between each pixel and the regional mean.

**Example output.** "Regional mean +0.1%/decade (not significant); 31% of the area is significantly greening and 18% browning; the cancellation index of 0.74 means the average hides most of the change."

## 3. Coherent opposite-sign regions: Local Moran HH/LL plus an EOF dipole

**Algorithm.**
1. Run `esda.Moran_Local` on the Sen-slope map (queen weights from `lat2W`, 999 permutations, then `esda.fdr`). High–High clusters are coherent rises; Low–Low clusters are coherent falls.
2. Run PCA on the cos-lat-weighted anomalies.
3. If EOF1 loadings have opposite signs over the HH and LL regions, that is consistent with one process driving both. Test the EOF1 eigenvalue with a permutation test.
4. Feed PC1 into PCMCI+ as a candidate driver.

**Libraries.** esda 2.10.0 (BSD-3) needs Python ≥ 3.12. scikit-learn is also used.

**Caveat.** Label this as exploratory. Method 1 is the confirmatory test.

## 4. Emerging hot-spot analysis (Esri method)

**Algorithm.**
1. Compute Gi* for each time step with `esda.G_Local(star=True)`. Double the one-sided `p_norm` and apply FDR.
2. Run Mann-Kendall on each pixel's Gi* series.
3. Classify each pixel as New, Consecutive, Intensifying, Persistent, Diminishing, Sporadic, Oscillating or Historical.

**Caveat.** Use annual bins, or the seasonal cycle will dominate. Source: the Esri "How Emerging Hot Spot Analysis works" documentation.

## 5. Per-pixel BEAST change-date map (verified working)

**Call.** `rb.beast123(Y, metadata, prior, mcmc, extra)` with a 3D cube, `whichDimIsTime=3` and `period=12`. Pass the arguments as positional `rb.args()` objects; a wrong positional string raises a SystemError.

**Test result.** 40×40×300 ran in about 62 s. With a true break at 2012.5, the recovered dates were 2011.9–2012.8.

**Output.** A map of the most likely change year, masked where cpPr < 0.5.

**Caveat.** Per-pixel cpPr is not calibrated the way our regional BEAST is. Either reuse that calibration or only flag pixels with cpPr > 0.8.

## 6. Time-of-emergence map

**Evidence.** Hawkins et al. 2020 (GRL 47:e2019GL086259, doi:10.1029/2019GL086259).

**Algorithm.** For each pixel, compute the signal (LOWESS anomaly against the first 10 years) and the noise (standard deviation of the residuals). Time of emergence is the first year after which S/N stays above 1 or 2. Calibrate the false-emergence rate on bootstrapped noise.

**Caveat.** About 25-year records leave short baselines, so many pixels will be "not emerged". Present that as a result, not as missing data.

## Data

- **Volume.** About 1.9 MB per variable at 40×40×300.
- **Sources.** GPM_3IMERGM, GLDAS_NOAH025_M and M2TMNXSLV via Cloud OPeNDAP. NDVI via an AppEEARS area task.

## Feasibility

| Methods | Time |
|---|---|
| 1 + 2 + 3 | about 1 day |
| 5 | about 3–4 h |
| 4 | about 4 h |
| 6 | about 3 h |

## Agent's top 2

1. Cluster-permutation field significance plus the "hidden by averaging" panel (methods 1 + 2).
2. Local Moran HH/LL plus the EOF dipole (method 3). If time allows, add per-pixel BEAST (method 5).
