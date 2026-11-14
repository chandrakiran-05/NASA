# Agent 3: AI-assisted discovery lens

## Endpoints verified live (2026-11-14)
- **Giovanni configured-variables:** JSON, no auth.
- **CMR variables/collections:** return ScienceKeywords and DOI.
  - Example: MOD13A3 → "VEGETATION INDEX > NDVI", DOI 10.5067/MODIS/MOD13A3.061.
- **GCMD KMS:** `https://cmr.earthdata.nasa.gov/kms/concepts/concept_scheme/sciencekeywords?format=json`. Official NASA keyword list: 3,784 concepts, v25.2, open.
- **NTRS API:** `https://ntrs.nasa.gov/api/citations/search?q=...`. Open, no key needed.
  - Example: "NDVI trend Sahel" → 20150018274, "Re-Greening Sahel: 30 Years…".
- **NASA ADS API:** `https://api.adsabs.harvard.edu/v1/search/query` returns 401 without a key. It is NASA-funded and needs a free token, so it is optional.
- **AppEEARS /product:** lists MCD12Q1.061 (land cover) and MCD12Q2.061.

## 1. "Trend Scan": scan a region, rank results with FDR
- **Pitch:** Draw a box and press Scan. The tool tests 15–30 catalog variables suited to the region and shows the strongest trends that survive a false-discovery-rate (FDR) correction.
- **New:** The baseline answers "is X trending here?". This answers "what is changing here?", and Benjamini–Hochberg across variables prevents p-hacking.
- **Data:** Giovanni Harmony area-average for monthly collections (GPM_3IMERGM, GLDAS_M, MERRA-2, AIRS). AppEEARS is optional because it takes about 15 minutes per task.
- **Guardrails:**
  - The candidate list is fixed and uses catalog IDs only.
  - The same deterministic ⑥ engine runs every test.
  - All non-significant results are shown, e.g. "12 tested, 3 significant after FDR".
- **Implementation:**
  - ② `POST /api/scan` (batch jobs).
  - ⑥ Reuse the FDR code from `/compare`.
  - ① Ranked leaderboard with sparklines.
  - ⑦ Precompute 2–3 demo regions.
- **Feasibility:** Medium.
  - Risk: the Giovanni quota (size unknown) and latency.
  - Mitigation: cap at about 12 variables and cache results.
- **Wow moment:** Draw a box over the Sahel or the Amazon arc of deforestation. The top 3 significant trends appear, each with a rate per decade and an FDR q-value.
- **Scores:** Impact 9 · Novelty 8 · Feasibility 6 · Rigor 9 · Demo 9.

## 2. "Ask the Catalog": question → ranked variables with citations
- **Pitch:** Ask "Is the air over Delhi getting dirtier?" and get ranked variables: OMNO2d NO₂, OMI aerosol index and MERRA-2 aerosol. Each comes with a reason and a NASA paper.
- **Data:** Giovanni configured-variables, AppEEARS /product, CMR (definitions, keywords, DOI), GCMD KMS synonyms, and NTRS papers (ADS optional).
- **Guardrails:**
  - The LLM can only output IDs from a closed enum, and the server rejects any unknown ID.
  - Reasons must quote CMR or GCMD text.
  - Citations are rendered from API fields.
  - The LLM never sees or emits data values.
  - If nothing fits, the answer is "no matching NASA variable".
  - An optional LLM rephrasing of the verdict is checked by a number validator against the result JSON.
- **Implementation:**
  - ③ Embeddings index plus GCMD synonym expansion.
  - ② `GET /api/suggest?q=`.
  - ① A free-text first step in the wizard.
- **Feasibility:** High. Risk: NTRS relevance is noisy, so present the papers as "related reading".
- **Wow moment:** A plain-English question returns a ranked list, with a DOI and a real NASA paper next to each variable.
- **Scores:** Impact 8 · Novelty 7 · Feasibility 9 · Rigor 7 · Demo 8.

## 3. "Region Fingerprint": land-cover-driven suggestions
- **Pitch:** Read MODIS land cover (MCD12Q1) for the box, e.g. "62% evergreen broadleaf, 8% urban". An auditable rule table then maps IGBP class → GCMD keywords → catalog IDs.
- **New:** Makes the challenge's "SI by region type" idea data-driven. Land-cover change can itself be a trend.
- **Guardrails:**
  - The rule table is versioned JSON, with a GCMD citation per row.
  - The percentages come from the product, not from an LLM.
- **Implementation:**
  - ④ An AppEEARS land-cover task.
  - ③ A `region_type` filter.
  - ① A pie chart in the wizard.
  - It feeds the candidate list for idea 1.
- **Feasibility:** Medium. Risk: AppEEARS takes about 15 minutes per task.
- **Wow moment:** Draw a box over the Ganges delta. It reports "mangrove wetland, cropland, urban" and suggests variables for each class.
- **Scores:** Impact 7 · Novelty 8 · Feasibility 6 · Rigor 8 · Demo 7.

**Agent recommendation:** Make #2 the front door and #1 the headline feature. Treat #3 as a stretch goal that feeds #1. The AI only selects and explains; every number comes from ⑥.
