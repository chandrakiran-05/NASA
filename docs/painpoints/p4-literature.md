# Problems scientists report in recent literature

Each citation was checked against a publisher page, Crossref, NTRS or a repository record, as noted in the Status column. Papers from before 2020 are marked as foundational.

| # | Problem | Citation | Status | Feature idea |
|---|---|---|---|---|
| 1 | Autocorrelation and the choice of prewhitening change MK p-values and Sen's slope; plain MK gives many false positives | Collaud Coen et al. 2020, AMT 13:6945, doi:10.5194/amt-13-6945-2020 | opened | Three MK variants side by side, with a "robust only if all agree" badge |
| 2 | Per-gridcell tests overstate significance: global greening area dropped from **35.2% to 15.3%** after FDR correction | Cortés et al. 2021, GRL 48:e2020GL091496, doi:10.1029/2020GL091496; Wilks 2016, BAMS, doi:10.1175/BAMS-D-15-00267.1 | abstract opened; Wilks pre-2020 | Toggle between raw p and FDR, plus "% of area significant before vs after" |
| 3 | Spatial autocorrelation makes false positives cluster into fake patterns | Cortés et al. 2020, Environ. Ecol. Stat., doi:10.1007/s10651-020-00446-4 | abstract opened | Field-significance block-permutation test |
| 4 | MODIS Terra/Aqua orbital drift biases products (Terra after 2020: Greenland albedo bias of about +0.01) | Twedt et al. 2023, SPIE, ntrs.nasa.gov/citations/20240001409; Feng et al. 2024, Sci. Remote Sens. 9:100116, doi:10.1016/j.srs.2023.100116 | NTRS record seen; metadata only | Sensor-event timeline: Terra drift from Feb 2020, Oct 2022 exit, collection changes |
| 5 | Changes across sensors and product versions create spurious NDVI trends | Jeong et al. 2024, RSE 311:114282, doi:10.1016/j.rse.2024.114282 | abstract via snippets | Terra vs Aqua comparison; flag a possible instrument effect |
| 6 | Changes to the observing system (SSM/I 1987, AMSU 1998) introduce spurious precipitation and P–E trends in the MERRA reanalyses; MERRA-2 reduced but did not remove them | Gelaro et al. 2017, J. Climate, doi:10.1175/JCLI-D-16-0758.1 (PMC6999672) | pre-2020; confirmed | Breakpoint test at known dates; trend computed separately on each side |
| 7 | IMERG trends agree with gauges 86.7% of the time in the GPM era but only 75.3% in the TRMM era, because calibration changed | Zhu et al. (incl. Huffman) 2024/25, ERL 20:014064, doi:10.1088/1748-9326/ad984e | metadata confirmed; abstract via snippet | Split IMERG at June 2014; add a "product fitness for trends" label |
| 8 | 22 precipitation products disagree; reanalyses split into wet and dry camps | Alexander, Contractor et al. 2020, ERL 15:055002, doi:10.1088/1748-9326/ab79e2 | abstract via repository | Product-agreement panel (sign agreement) |
| 9 | Searching for "pause" or "acceleration" windows is hidden multiple testing | Rahmstorf, Foster & Cahill 2017, ERL 12:054001, doi:10.1088/1748-9326/aa6825 | pre-2020; abstract seen | Trend triangle |
| 10 | Record length needed to detect a trend depends on noise, autocorrelation and level shifts | Weatherhead et al. 1998, JGR (DOI not confirmed); EGUsphere-2024-2627 preprint (ozone) | pre-2020, not opened; preprint | Message: "your record is X of the Y years needed" |
| 11 | Remote-sensing research is hard to reproduce | Kedron & Frazier 2022, Remote Sensing 14:5471, doi:10.3390/rs14215471 | metadata confirmed | One-click provenance export: JSON plus a Python script |
| 12 | Communicating uncertainty; ensembles help | Merchant et al. 2017, ESSD 9:511, doi:10.5194/essd-9-511-2017 | pre-2020; abstract seen | Calibrated confidence statement |

No peer-reviewed paper from 2020 or later on start/end-date selection was found.

## Agent's top 3 picks
1. Trend triangle plus robustness badge (items 1 and 9).
2. Instrument-change detector (items 4–7).
3. FDR significance map plus provenance export (items 2, 3 and 11).
