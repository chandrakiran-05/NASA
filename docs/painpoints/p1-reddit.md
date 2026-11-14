# Pain points from Reddit

**How the evidence was gathered:**
- Reddit could not be opened directly (it was blocked for WebSearch, WebFetch and the Browser pane).
- The agent used DuckDuckGo `site:reddit.com` searches instead and read the result titles and snippets.
- Every item is **search snippet only**. The URLs are real, but the full threads were not read.
- Dates are estimated from the post IDs.

| # | Pain point | Who | Evidence (search snippet only) | Frequency | Feature idea |
|---|---|---|---|---|---|
| 1 | Users download a whole product (about 11 GB of IMERG) when they only need regional monthly numbers | ecology and hydrology students | reddit.com/r/ecology/comments/ec5l3u; r/gis/comments/y3ol3h; r/gis/comments/rimp1c | high (~4) | Server-side subsetting and area averaging that returns a CSV, not gigabytes |
| 2 | Averaging a gridded netCDF over an irregular region (state, basin, shapefile) | GIS and hydrology students | r/gis/comments/18zn2yc; r/gis/comments/1dskxyo; r/Hydrology/comments/hsqez8; r/oceanography/comments/1425my2 (530 monthly files) | high (6+) | Draw or upload a polygon and get an area-weighted mean series with a pixel count |
| 3 | HDF4/HDF-EOS files are hard to open and convert | beginners using QGIS/R | r/gis/comments/1cx3gtm; r/gis/comments/ep1aft; r/gis/comments/1ap4fw4; r/askgis/comments/1ap4wbu | high (5+) | Hide file formats entirely and return analysis-ready tables |
| 4 | QA bitflags and cloud masks are confusing and differ between products | RS grad students | r/remotesensing/comments/tqxyqi; r/remotesensing/comments/hqqegz | med-high (4+) | QC strictness slider showing the observations that survive, with plain-language labels |
| 5 | Scale factors, offsets and units produce wrong values | students | r/remotesensing/comments/znlcqs; r/ArcGIS/comments/1104vrl; r/Hydrology/comments/11l05hx | medium (3+) | Automatic scale and unit harmonization plus a physical-range sanity check |
| 6 | Mann-Kendall assumptions (autocorrelation, seasonality): which series do I test? | stats-literate students | r/AskStatistics/comments/13vx8uh; r/AskStatistics/comments/17kbcj3 | high (~9 threads) | Automatic autocorrelation check and switch to a modified or seasonal MK, with the reason shown |
| 7 | Contradictory results, e.g. a significant MK alongside a Sen's slope of 0, or not understanding S and tau | hydrology analysts | r/AskStatistics/comments/rki0dv; r/statistics/comments/15qgkk4 | medium | "Why this result" panel covering ties, zero-inflation and a plain-language reading |
| 8 | Gaps in the record undermine the trend test (a regulator rejected one) | consultants | r/statistics/comments/r5z1p1; r/gis/comments/p5y95m | medium | Completeness bar plus a warning below a set threshold |
| 9 | Trend software costs money (XLSTAT is about $1k) | students and practitioners | r/statistics/comments/txa0tm | low-med | Free browser-based tests with exportable code |
| 10 | Products disagree with each other and with stations (ERA5 vs stations by more than 25%) | meteorology users | r/meteorology/comments/es9r40; r/Hydrology/comments/11l05hx | medium | Multi-product agreement view with a robust/disputed badge |
| 11 | Overwhelmed choosing a dataset; Giovanni "not very intuitive" | beginners | r/gis/comments/u6mili; r/gis/comments/18xf9h1; r/civilengineering/comments/14xu5rj | med-high | Question-first variable picker |
| 12 | Have NDVI maps but don't know how to test whether the change is significant | GIS students | r/gis/comments/tyzcyp | medium | One-click NDVI trend test with a plain-language result |

## Agent's top 3 to build in 48 hours
1. **Polygon to analysis-ready series** (items 1–3, 5).
2. **A trend test that checks its own assumptions** (items 6–8).
3. **A product-agreement check** (item 10).

## Caveats
- Search results lean toward older posts (2019–2021).
- No Reddit posts named Giovanni, AppEEARS, GLDAS or OPeNDAP specifically.
