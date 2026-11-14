# R2: Claim verification upgrades for Research Evidence

Every citation was checked against arXiv, ACL Anthology, Crossref or Cochrane. Licences were checked on the Hugging Face API and PyPI.

## 1. Sentence-level NLI stance (replaces the keyword lexicon)

- **Why:** NLI handles negation, hedging and direction words that belong to other variables, which the lexicon gets wrong.
- **Citations:**
  - SciFact: Wadden et al., EMNLP 2020, arXiv:2004.14974
  - SummaC: Laban et al., TACL, arXiv:2111.09525. Comparing sentence pairs works far better than comparing whole documents.
  - SciFact-Open: arXiv:2210.13777. Open-domain F1 drops by 15 points or more.
- **Models (CPU):**

  | Model | License | Size | Note |
  |---|---|---|---|
  | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | MIT | ~184M | MNLI 0.903; label order entailment / neutral / contradiction (check `config.id2label`) |
  | `cross-encoder/nli-deberta-v3-small` | Apache-2.0 | ~0.1B | fallback |
  | `lytang/MiniCheck-DeBERTa-v3-Large` | MIT | ~0.4B | MiniCheck (EMNLP 2024, arXiv:2404.10774) reaches GPT-4-level grounding at about 400× lower cost |

- **Algorithm:**
  1. Split the abstract into sentences sᵢ.
  2. Build two contrastive hypotheses: H+ = "NDVI increased in the Sahel" and H− = "NDVI decreased in the Sahel".
  3. Score each sentence: sᵢ = P_ent(sᵢ,H+) − P_ent(sᵢ,H−). Keep the sentence with the largest |sᵢ|.
  4. Label it supports if s ≥ τ, conflicts if s ≤ −τ, otherwise neutral.
  5. Scope gate: the chosen sentence or the title must name both the variable and the region. If not, label it "related, not on-scope".
  6. Calibrate scores with temperature scaling (Guo et al. 2017, arXiv:1706.04599) on about 100 labelled pairs. Set τ ≈ 0.5 for about 90% precision.
- **Cost:** about 400 sentence pairs take 20–60 s on CPU. Cache results by DOI.
- **Feasibility:** 48 hours, yes.

## 2. Paper-reported rate vs our slope

- **Citations:**
  - Dagdelen et al. 2024, Nat. Commun. 15:1418, doi:10.1038/s41467-024-45563-x
  - CQE: Almasian et al. 2023, arXiv:2305.08853
- **Tools:**
  - `quantulum3` (MIT)
  - Regex for rates and year periods
  - Qwen extraction for hard cases, accepted only with a verbatim-span check
- **Algorithm:**
  1. Normalise units.
  2. Compute period overlap as the intersection over the union. If it is below 0.5, mark the pair "not comparable".
  3. Compute z = (b_p − b_o) / √(se_p² + se_o²). If the paper gives no standard error, derive one from its confidence interval; if there is none, assume 50% of |b_p| and flag it.
  4. Verdict:
     - consistent if |z| < 2
     - same sign but a different magnitude otherwise
     - opposite if the signs differ
- **Output example:** "Paper +0.30 °C/decade (1980–2020); ours +0.27 ± 0.05 (1981–2020): consistent, z = 0.5."
- **Feasibility:** 48 hours, yes for the regex path.

## 3. Random-effects pooling and a sign test

- **Basis:** Cochrane Handbook chapter 12:
  - §12.2.1.3: vote counting by direction of effect, with a sign test, is OK.
  - §12.2.2.1: vote counting by significance is unacceptable.
- **Tools:**
  - `statsmodels.stats.meta_analysis.combine_effects` (Paule–Mandel, `use_t=True`)
  - `scipy.stats.binomtest`
- **Output:** forest plot with a "Satellite (this analysis)" comparator row. Our own estimate is not pooled with the papers.
- **Rules:**
  - Do not pool when fewer than 3 papers report a rate.
  - Cluster papers that use the same dataset (e.g. GIMMS, MODIS).

## 4. Retraction and venue-integrity flags (a few hours)

- **Data sources:**
  - OpenAlex `is_retracted`: 144,624 works
  - OpenAlex sources `is_in_doaj`: 23,670 sources
  - Crossref `update-to[].type == "retraction"`, from Retraction Watch or the publisher: 81,613 records
- **Effect on trust weight:**
  - Retracted: trust 0, shown struck through
  - Expression of concern: trust × 0.3
  - Correction: badge only
- **API key:** OpenAlex now applies a daily budget to calls made without a key. Register a free key.

## 5. Recency-weighted consensus index

- **Basis:** Cook et al. 2013, ERL 8:024024, doi:10.1088/1748-9326/8/2/024024. It reports agreement only among papers that take a position.
- **Algorithm:**
  1. Weight each paper: w = trust × relevance × 0.5^(age / 8 yr).
  2. Report the weighted support share with a Wilson interval.
  3. Add a fourth state, "contested", when the interval crosses 0.5.
  4. Check for a recent shift by splitting papers before and after 2015.
- **Future work:** scite (QSS 2021, doi:10.1162/qss_a_00146) is commercial.

## 6. Guardrails for Qwen as a judge

- **Basis:** Zheng et al., NeurIPS 2023, arXiv:2306.05685. LLM judges show position, verbosity and self-enhancement bias.
- **Rules:**
  - Call Qwen only when NLI is unsure.
  - Run each judgement twice with the hypotheses swapped, and accept only if both runs agree and the quote is verbatim.
  - Report Cohen's κ against NLI.
- **Gold set:** ClimateCheck (SDP@ACL 2025, doi:10.18653/v1/2025.sdp-1.24). Its best F1 was 0.73.

## Agent's top 2

1. Sentence-level NLI with contrastive hypotheses and calibration.
2. Paper-reported rate vs our slope, plus retraction flags (cheap to add).
