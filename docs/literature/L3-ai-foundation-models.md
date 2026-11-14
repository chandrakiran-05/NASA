# L3 — AI and foundation models for EO time series (agent report, verified Nov 2026)

## 1. Chronos-Bolt / Chronos-2 probabilistic forecast band
- **Papers:**
  - Ansari et al. 2024, "Chronos: Learning the Language of Time Series", arXiv 2403.07815 (TMLR). https://arxiv.org/abs/2403.07815
  - Ansari, Shchur et al. 2025, "Chronos-2: From Univariate to Universal Forecasting", arXiv 2510.15821.
- **Availability:** `pip install chronos-forecasting`, Apache-2.0.
  - Bolt models: 9M, 21M, 48M and 205M parameters. They run on CPU and are up to 250x faster than the original Chronos.
  - Chronos-2: 120M parameters (28M small variant). It accepts covariates.
- **Output:** a forecast band to 2030 (10–90% quantiles), plus P(2030 value > baseline). A single CPU call takes seconds on 300–500 monthly points.
- **Limits:** this is a statistical extrapolation, not a climate projection. It is not a significance test, so keep MK/Sen for that.

## 2. Evidence that Chronos works on hydrology (snippet-level)
- arXiv 2505.01415 (2025), Everglades water levels: Chronos was the best zero-shot model among 5 foundation models and 12 task-specific models. TimesFM, Moirai and Timer were weaker. All models struggled with abrupt changes.
- arXiv 2511.11849 (2025), CAMELS-US: models given exogenous inputs beat zero-shot foundation models.
- **Licenses of alternatives:**
  - TimesFM (arXiv 2310.10688): Apache up to v2.5; v3.0 is reportedly non-commercial.
  - Moirai: CC-BY-NC.
  - Lag-Llama: Apache.

## 3. Anomaly-month flagging
- Liu & Paparrizos, TSB-AD, NeurIPS 2024 D&B. https://thedatumorg.github.io/TSB-AD (`pip install TSB-AD`, about 1,070 series, 40 algorithms).
- **Method:** flag a month when the observed value falls outside Chronos's rolling one-step 98% interval, then cross-check it with a robust STL-residual z-score.
- **Label it as** "statistically unusual", not "extreme event".

## 4. Prithvi (NASA/IBM): mention only
- **Prithvi WxC:** arXiv 2409.13598. 2.3B parameters, trained on 160 MERRA-2 variables. HF `ibm-nasa-geospatial/Prithvi-WxC-1.0-2300M`, CDLA-Permissive-2.0. Needs a global 6-hourly gridded state and a GPU.
- **Prithvi-EO-2.0:** arXiv 2412.02732. Works on HLS image chips.
- **Fit:** poor for regional monthly means. List it as future work.

## 5. Prior work on LLM agents for climate data
- **ClimSight:** Koldunov & Jung 2024, Commun. Earth Environ.; Kuznetsov et al. 2025, npj Climate Action 4:97, doi:10.1038/s44168-025-00300-y. Code: github.com/clidyn/climsight.
- **GeoAgent:** arXiv 2410.18792. LLMs hallucinate rarely used geospatial libraries; executing the code plus RAG helps.
- **Data Interpreter:** arXiv 2402.18679. A plan → code → verify agent.
- **ClimateGPT:** arXiv 2401.09646. A text chatbot, not useful for this project.
- **Gap:** none of these attaches a statistical, per-claim guarantee to what the LLM says about a specific NASA series.

## 6. Use the LLM as a judge, not as the reader of raw numbers
- Merrill et al., "Language Models Still Struggle to Zero-shot Reason about Time Series", Findings EMNLP 2024 (arXiv 2404.11757). LLMs score marginally above chance and up to 30 points below humans.
- "LLM-as-a-Judge for Time Series Explanations", arXiv 2604.02118 (Apr 2026, under review). LLMs are unreliable when generating explanations but much more reliable when verifying them against the data. Benchmark: TSQueryBench.
- **Design:** the LLM writes only from a fact JSON. A verifier pass then checks every claim.

## 7. Context-aided forecasting
- Williams et al., "Context is Key", ICML 2025 (arXiv 2410.18959), 71 tasks. Text such as "strong El Niño" or "dam built in 2010" can be turned into covariates or breakpoints.
- Feasibility: medium. Merrill found the benefit inconsistent.

## Agent's top 2
1. **Verified Trend Brief:** stats + Chronos produce a fact JSON → Qwen writes the explanation → a verifier checks it → a "claims verified 9/9" badge.
2. **Chronos probabilistic outlook + anomaly flags.**

**Gimmicky (avoid):** claiming Prithvi is integrated, a generic chatbot, letting Qwen read raw series, or calling an extrapolation a "projection".
