# Pain points from NASA user channels (Earthdata Forum, Giovanni guide, ACSI, GitHub)

**Access note:** The Earthdata Forum was unavailable, so forum items are **search snippet only**. The ARSET Q&A PDFs redirect away from the original links. All other sources were opened.

| # | Pain point | Who | Evidence | Feature idea |
|---|---|---|---|---|
| 1 | The Giovanni time-series API returns single points only, with no area average | researchers, devs | forum.earthdata.nasa.gov/viewtopic.php?p=25242 (snippet; GES DISC staff) | Our own area-weighted regional mean behind one call |
| 2 | A Cloud Giovanni bug inserted spurious blocks of zeros into 10 GLDAS/MERRA-2/NLDAS/GRACE collections, for data before 2024. Found Nov 2025, fixed 26 Mar 2026. No guidance was given for data already downloaded. | researchers | earthdata.nasa.gov/data/alerts-outages/reprocessed-hydrology-products-available-from-cloud-giovanni (opened) | Integrity check for runs of zeros or constant values, plus a provenance timestamp |
| 3 | Requests return "data is all fill values" (the guide lists 8 causes) | students, applied users | giovanni.gsfc.nasa.gov/giovanni/doc/UsersManualworkingdocument.docx.html (opened); forum p=8238 (snippet) | Valid-pixel coverage % per time step, with low-coverage steps excluded |
| 4 | Monthly-rate units (mm/month) bias the series because months differ in length | researchers | Giovanni user guide (opened) | Days-in-month normalization |
| 5 | **Giovanni's regression line "does not draw a scientific trend conclusion"**: no significance test and no deseasonalizing | researchers, students | Giovanni user guide (opened) | Seasonal Mann-Kendall + Sen's slope + autocorrelation correction, explained in plain language |
| 6 | Guests are limited to 4 time points, and request size is capped | students | Giovanni user guide (opened) | Automatic chunking and stitching |
| 7 | Version and reprocessing seams (MERRA-2 stream 401; GLDAS-2.0 vs 2.1 forcing) | researchers | forum p=22065 (snippet); GLDAS snippet | Mark version boundaries on the chart and run a change-point test at each one |
| 8 | Searches silently return `[]` because the data sits in a sibling collection (GRACE vs GRACE-FO), which a user called "just baffling" | new users | github.com/earthaccess-dev/earthaccess/issues/1434 (opened) | Pre-check against CMR temporal and spatial coverage, and suggest sibling collections |
| 9 | Building a series from many granules runs out of memory or loses auth (crash at about 7,000 granules) | researchers | github.com/earthaccess-dev/earthaccess/issues/499 (opened, ~22 comments) | Reduce the data server-side and never download full granules |
| 10 | AppEEARS jobs stuck in pending (CMR backlog) | applied users | forum p=25161, p=25062 (snippets, late 2025 – Jan 2026) | Job status display, fallback source, cache |
| 11 | Users want monthly means of daily data without downloading everything | hydrology researchers | forum p=24596 (snippet) | On-the-fly aggregation with a completeness threshold |
| 12 | Documentation is the weakest satisfaction driver (83), and students, teachers and devs score lower (78 vs 79 overall) | students, educators | earthdata.nasa.gov/learn/articles/2022-acsi-summary (opened); gpm.nasa.gov/resources/faq/what-are-imerg-variables-giovanni (opened) | Per-dataset caveats panel |
| + | Users ask for polygon or shapefile input in place of a bbox | devs | github.com/earthaccess-dev/earthaccess/issues/279 (opened) | Draw or upload GeoJSON |
| + | The GES DISC subsetting web service is being deprecated | devs | github.com/nasa/gesdisc-tutorials/issues/211 (opened) | Endpoint health check with a fallback |

## Agent's top 3 picks
1. Trend significance (#5): fills a gap stated in Giovanni's own guide.
2. Data-quality checks on every series (#2–4): respond to an official NASA bug alert.
3. Coverage and version-seam pre-check (#7–8).
