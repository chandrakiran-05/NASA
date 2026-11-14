# Shared brief: complete aesthetic rebuild

Owner request, 15 November 2026: rebuild the whole site, research multiple Awwwards/showcase examples, propose original directions, debate them and choose the strongest implementation. The user delegates design decisions to this team; do not stop for another aesthetic questionnaire.

## Product truth

Earth System Trend Detective is a NASA Space Apps tool for students and science-literate users: ask about an Earth variable and region, fetch official NASA/NOAA records, show the time series and test magnitude/significance honestly. The headline must communicate this, not just global warming. Source: docs/01-challenge.md and https://www.spaceappschallenge.org/2026/challenges/earth-system-trend-detective/ . Read CLAUDE.md for backend rules.

## Requirements carried from the user's prior requests

1. Smooth, fast experience; the user rejected lag and generic AI-looking design twice.
2. Small official NASA logo at header left. No Heat explorer or The project header links. Features + Try AirLLM at right; AirLLM has a real explanation/setup/download page.
3. A realistic, centered, interactive spinning 3D Earth. Thin geographic grid overlay. Drag/keyboard accessible.
4. Oversized aesthetic hero text behind/around Earth, but readable. Distinct vibrant palette, purposeful background flow, restrained premium pointer response.
5. Compact rounded transparent glass prompt with a round send button. Small DigiTwin entry underneath.
6. Typing India/Africa/states/cities focuses Earth. Temperature/rainfall/weather/vegetation words create labeled illustrative topic reactions. Never invent weather, observational heat maps or scientific numbers.
7. DigiTwin changes the world: same Earth persists, rolls 180 degrees upside-down, a brief dreamy blur/text/palette transition. Heading explains a possible world under assumptions. Same prompt selects twin mode. A return control reverses everything and preserves observed state.
8. Below DigiTwin: real workflow and data structure. Existing scenario controls/data uploads/results must remain functional. Observed mode's features should be short and minimal.
9. Rebuild EVERY surface coherently: hero, short explanatory sections, observed evidence, DigiTwin forms/results, AirLLM page. No superficial CSS-only recolor.
10. Do not create or edit backend endpoints. Do not merge/switch backend branches.

## Exact implementation context

Workspace: C:/Users/Danio Stracy/Desktop/NASA . React19 + TypeScript + Vite6 + Three.js0.180; lucide-react; lazy Plotly BASIC distribution. Current files frontend/src/{App,Globe,ObservedEvidence,TwinLab,AirLLM,api,twinApi,promptContext,Narrative,EvidenceChart}.tsx/.ts plus styles.css/air.css.

Git refreshed this session: main/frontend b3835e4; backend-active-trends ecf2892; research-evidence33deaba. Actual DigiTwin engine and registered /api/twin routes exist in backend-active-trends. Current main runtime at8000 lacks twin and returns404. The UI must report capability absence honestly. No forecast substitution.

Observed API: /api/ai/plan, /api/investigate + jobs, /regions/search, /ai/ask, uploads, analyze, integrity/court/clock and export. All browser calls go through typed API client; credentials server-only; all numeric statistics backend-only; missing values gaps; provenance and caveats accessible.

Twin API already implemented: GET/POST /api/twin; GET /{id}; POST /{id}/data, /data-csv, /import {series_id,name?}; /simulate {horizon_years:1..100,n_runs:50..2000,seed,compare_to_baseline,scenario:{variable:{trend_multiplier,trend_add_per_decade,shocks,drivers,threshold}}}. Responses simulated p05,p50,p95, reference/delta, threshold probabilities/disclaimer. At least24 valid observations; no NLP twin planner. Never silently derive numeric scenario knobs from prose.

## Performance truths to preserve

Globe is one persistent scene across modes, DPR<=1.25,64x32 sphere, combined line grid, draw scheduling stops offscreen/hidden/settled paused; idle30fps budget, interactive fullRAF. Pause/offscreen measured0 renders. Returning world restores separate observed/twin question/location states. Basic Plotly lazy378KB gzip, reduced from1.47MB; do not regress hero loading or add expensive postprocessing. CSS glass blur only small prompt; no full-screen animated blur, cursor trails, second renderer, scroll-jacking or autoplay blocking loader.

## Research/debate assignment

Browse accessible Awwwards category/site profiles AND a minimum of two actual reference sites per agent when possible. Inspect visuals via browser/screenshots where possible, not only marketing text. Extract exact URLs, observed composition/type/palette/motion/navigation ideas, and separate observation from inference. No copying distinctive art/code, no fabricated awards/metrics, no arbitrary external assets.

Each researcher proposes ONE original direction specifically for this project: name, first viewport layout, type voices, colors, Earth treatment, prompt design, twin transformation, below-fold product story, evidence + forms, AirLLM, responsive and performance rules. Explain what it does differently from the current dark-globe-over-two-lines screen. Include weaknesses and measurable acceptance criteria. Then challenge the other agents' proposals for usefulness, originality, science clarity, accessibility and cost. Root selects a coherent direction; do not blend everything into soup.

Write only assigned research files under docs/design-research/. Do not change product code in the research phase. Keep each proposal <=900 words and each rebuttal concise. User asked for debate; be direct and reasoned, not performative.
