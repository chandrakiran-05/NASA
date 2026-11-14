# Platforms & APIs — verified reference

All facts below come from official docs or live calls made 2026-11-14. Anything not confirmed is marked **UNVERIFIED**. No third-party data sources are used in the pipeline. The only third-party pieces are the two stats articles the challenge itself lists, and they inform methods only.

## Role of each challenge resource

| Resource | Role in our project | Programmatic? |
|---|---|---|
| Giovanni / Hydrology Time Series | **PRIMARY** source for MERRA-2, GLDAS, GPM IMERG, AIRS, OMI time series | Yes: Giovanni-in-the-Cloud API |
| AppEEARS | **PRIMARY** source for MODIS/VIIRS land (NDVI, LST, ET, GPP), SMAP, DAYMET | Yes: REST API |
| NOAA CDO / NCEI | **PRIMARY** source for ground-station weather (validation and "local" view) | Yes: NCEI Access Data Service, plus CDO v2 |
| CMR (behind Giovanni/AppEEARS) | Variable/collection discovery and metadata (definitions, units) | Yes |
| SeaWiFS paper (NTRS) | Baseline methodology (OLS slope with p < 0.05, robust check) | n/a |
| Stats articles | Methods: OLS t-test, Mann-Kendall, Seasonal MK | n/a |
| KNMI Climate Explorer | Manual cross-check / reference only | **No documented API** |
| CSA RCM, Geo.ca | Context / links only (catalog metadata APIs; imagery needs EODMS ordering and SAR processing) | Metadata only |
| SWOT (CSA info → NASA PO.DAAC) | Optional stretch goal: lake/river levels; record only starts Dec 2022 | Yes (PO.DAAC/earthaccess) |

---

## 1. Earthdata Login (EDL) — shared auth
- Register for free at urs.earthdata.nasa.gov.
- **Bearer token** (`Authorization: Bearer <token>`): required by the Giovanni API and AppEEARS; accepted by CMR.
  - EDL user tokens are valid for 60 days, with at most 2 active at a time. Created via the GUI or `POST https://urs.earthdata.nasa.gov/api/users/token` (Basic auth).
- **`~/.netrc`** (`machine urs.earthdata.nasa.gov login … password …`): used by earthaccess and Cloud OPeNDAP.
- Tokens stay **server-side only**.

## 2. CMR Search API (discovery)
- Base URL: `https://cmr.earthdata.nasa.gov/search`
- Docs: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html

| Purpose | Call |
|---|---|
| Find variables | `GET /variables.json?keyword=<text>&page_size=…` (wildcards `*` and `?`; returns `associations.collections`) |
| Collection info | `GET /collections.json?short_name=M2T1NXSLV` → `C1276812863-GES_DISC` |
| Granules | `GET /granules.json?concept_id=…&temporal=…&bounding_box=…` |

- Paging: `page_size` up to 2000, with the `CMR-Search-After` header for further pages.
- Throttling: HTTP 429 plus `retry-after`. No numeric limit is published.

## 3. Giovanni in the Cloud API (GES DISC) — primary for atmosphere/hydrology
The old **Data Rods** CGI (hydro1…/timeseries.cgi) is **retired**; we do not use it. The classic giovanni.gsfc.nasa.gov UI has **no documented API**, so we do not script it.

| Endpoint | Purpose | Auth |
|---|---|---|
| `GET https://api.giovanni.earthdata.nasa.gov/configured-variables/` | List of 867 supported variable IDs, formatted `<ShortName>_<ver>_<Var>` | none |
| `GET https://api.giovanni.earthdata.nasa.gov/timeseries?data=<id>&location=[lat,lon]&time=<start>/<end>` | **Point** time series | Bearer |
| Harmony request (harmony-py): `Collection(id=<concept>)`, `spatial=BBox(w,s,e,n)`, `temporal`, `variables=[<id>]`, `average="area"`, `format="text/csv"` | **Area-averaged** time series (new Apr 2026) | Bearer |
| `GET https://api.giovanni.earthdata.nasa.gov/quota` | Fraction of monthly compute quota used | Bearer |

- `/timeseries` returns CSV: a 13-line header (`param_name`, `unit`, `lat`, `lon`…) followed by `Timestamp,value` rows. It is point-only.
- Harmony area output is CSV: a header block ending in a line containing only `,`, then `time,mean_<var>`.
- Sources:
  - nasa/gesdisc-tutorials, `How_to_Access_GiC_Time_Series_Service.ipynb`
  - nasa/gesdisc-tutorials, `How_To_Access_the_Giovanni_Averaging_Service_Using_Python.ipynb`
- Quota size is **UNVERIFIED**. There is no public OpenAPI page.
- **Active GES DISC alerts** must be surfaced in the UI:
  - Outage of some cloud Giovanni variables: AIRS3STD 7.0, GLDAS_NOAH025_3H 2.1, IMERG DE/DL/HHE/HHL, OMI daily products, and others.
  - Ocean grid cells are masked for land-model variables.
  - A spurious-zeros bug before 2024-01-01 in GLDAS 3H, MERRA-2 and NLDAS series. Fixed 2026-03-26.

### Key verified variables / collections

| Dataset | Short name (ver) | Concept ID | Res. | Giovanni ID example |
|---|---|---|---|---|
| MERRA-2 hourly single-level | M2T1NXSLV 5.12.4 | C1276812863-GES_DISC | 1 h | `M2T1NXSLV_5_12_4_T2M` |
| MERRA-2 monthly single-level | M2TMNXSLV 5.12.4 | C1276812859-GES_DISC | monthly | not in Giovanni → OPeNDAP fallback |
| GLDAS Noah 0.25° 3-hourly | GLDAS_NOAH025_3H 2.1 | C1342986035-GES_DISC | 3 h | `GLDAS_NOAH025_3H_2_1_Tair_f_inst` |
| GLDAS Noah 0.25° monthly | GLDAS_NOAH025_M 2.1 | C1342986036-GES_DISC | monthly | v2.0 IDs listed; v2.1 **UNVERIFIED** |
| GPM IMERG Final daily | GPM_3IMERGDF 07 | C2723754864-GES_DISC | daily | `GPM_3IMERGDF_07_precipitation` |
| GPM IMERG Final monthly | GPM_3IMERGM 07 | C2723754851-GES_DISC | monthly | `GPM_3IMERGM_07_precipitation` |
| AIRS L3 | AIRS3STD / AIRS3STM | (see research) | daily / monthly | `AIRS3STD_006_SurfAirTemp_A` |
| OMI NO₂ | OMNO2d 003 | C1266136111 | daily | `OMNO2d_003_ColumnAmountNO2TropCloudScreened` |
| OMI ozone / aerosol index | OMTO3d 003 | C1266136070 | daily | `OMTO3d_003_ColumnAmountO3` |

## 4. Cloud OPeNDAP + earthaccess — fallback for variables Giovanni doesn't serve
- URL pattern: `https://opendap.earthdata.nasa.gov/collections/<concept-id>/granules/<ShortName>.<ver>%3A<file>.dap.nc4?dap4.ce=/T2M`
- Requests go **one granule at a time**. A time series is a loop over granules, which is slow, so the results are cached.
- On-premises GES DISC OPeNDAP was retired Aug–Sep 2026; we do not use it.
- earthaccess (`login`, `search_data`, `search_datasets`) is used to find granule URLs.

## 5. AppEEARS API (LP DAAC) — primary for land surface
- Base URL: `https://appeears.earthdatacloud.nasa.gov/api`
- Docs: https://appeears.earthdatacloud.nasa.gov/api/

| Step | Call |
|---|---|
| Login | `POST /login` (Basic EDL) → token (about 48 h) |
| Products | `GET /product`; layers via `GET /product/{id}` (FillValue, ScaleFactor, ValidMin/Max, Units) |
| Submit | `POST /task` with `task_type` `point` (coordinates) or `area` (GeoJSON, `output.format` netcdf4) |
| Poll | `GET /status/{task_id}` or `GET /task/{task_id}` (pending → processing → done) |
| Files | `GET /bundle/{task_id}` → `GET /bundle/{task_id}/{file_id}` (302 to S3; follow redirects) |
| Quality decode | `GET /quality/{product}/{layer}/{value}` |

- Dates are `MM-DD-YYYY`.
- Tasks are **asynchronous** and typically take around 15 minutes; the UI must handle this.
- Request-size limits are **UNVERIFIED**.
- Whether CSV values come pre-scaled is **UNVERIFIED**. We always mask using the `/product/{id}` metadata.
- **GPM is NOT in AppEEARS**, so precipitation comes from Giovanni.

Verified products (all from 2000-02 to present unless noted):

| Variable | Product ID | Res. |
|---|---|---|
| NDVI/EVI monthly | MOD13A3.061 (layer `_1_km_monthly_NDVI`) | 1 km, monthly |
| NDVI/EVI 16-day | MOD13Q1.061 (`_250m_16_days_NDVI`) | 250 m |
| Land surface temp | MOD11A2.061 (`LST_Day_1km`, `LST_Night_1km`) | 1 km, 8-day |
| Evapotranspiration | MOD16A2GF.061 (`ET_500m`) | 500 m, 8-day |
| GPP | MOD17A2HGF.061 | 500 m, 8-day |
| Snow cover | MOD10A2.061 | 500 m, 8-day |
| Burned area | MCD64A1.061 | 500 m, monthly |
| Soil moisture | SPL3SMP_E.006 (from 2015-03) | 9 km, daily |
| Weather (N. America) | DAYMET.004 (1950–2025) | 1 km, daily |

## 6. NOAA NCEI — station observations
**Primary: NCEI Access Data Service** (no token needed; verified live).
- Request: `GET https://www.ncei.noaa.gov/access/services/data/v1?dataset=global-summary-of-the-month&stations=USW00094728&startDate=2000-01-01&endDate=2020-12-31&dataTypes=TAVG,TMAX,TMIN,PRCP&format=json&units=metric`
- Values come back as strings. Docs: https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation
- Rate limits are **UNVERIFIED**.

**Fallback: CDO Web Services v2.**
- Endpoint: `https://www.ncei.noaa.gov/cdo-web/api/v2/{datasets|datatypes|stations|data}`
- Auth: header `token: <free token>`.
- Limits: 5 requests/s and 10,000/day. Results capped at 1000 rows per request.
- Monthly data is limited to 10-year windows; daily data to 1-year windows.
- Use for station discovery near the user's region.

## 7. Statistics stack (methods from the listed resources)

| Method | Library function | Source of method |
|---|---|---|
| Deseasonalize | `statsmodels.tsa.seasonal.STL(period=12, robust=True)` | Challenge "Working with the data" |
| OLS slope + t-test + 95% CI | `statsmodels.api.OLS` / `scipy.stats.linregress` | SeaWiFS paper; Medium article |
| Mann-Kendall (autocorrelation-safe) | `pymannkendall.hamed_rao_modification_test` | Medium article; pymannkendall docs |
| Seasonal Mann-Kendall | `pymannkendall.seasonal_test(period=12)` | Medium article |
| Sen's slope + CI | `scipy.stats.theilslopes` | robust-slope check (SeaWiFS used robust regression) |
| Autocorrelation diagnostics | `statsmodels` `acf`, `durbin_watson` | Statsig guide (check test assumptions) |
| Multiple-region correction | `statsmodels.stats.multitest.multipletests` (FDR) | Statsig guide (multiple comparisons) |
