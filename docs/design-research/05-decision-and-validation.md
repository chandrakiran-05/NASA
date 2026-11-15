# Research tournament and build decision

## Brief

All three designers received docs/AGENT-DESIGN-BRIEF.md, which preserves the user's prior functional, visual, backend and performance instructions. Research proposals list exact source URLs and distinguish fetched-page observations from visual inference. Sources included accessible Awwwards profiles/live projects and Siteinspire references; not all WebGL sites loaded fully. No proprietary artwork/code was reused.

## Contenders

- Immersive: Field of Evidence, a navigable planetary exhibit. Strength: spatial continuity and a strong central object. Risk: another dark/glowing scene too close to the design the user rejected; navigation spectacle could obscure a real question.
- Editorial: Living Atlas / Field Atlas, a mineral-paper scientific publication with a living Earth. Strength: distinctive identity across hero, evidence, forms and field guide. Risk: becoming travel-magazine styling rather than a usable scientific tool.
- Product: Atlas Desk, a cobalt/chalk working atlas. Strength: prompt-place-result continuity and rigorous data surfaces. Risk: familiar GIS/product-dashboard styling.

## Critique and resolution

All researchers criticized another black-globe treatment. Product direction argued for Living Atlas over its own concept, provided the regional-data task remains legible, the Earth is lit naturally, and results/forms receive equal craft. Immersive agreed, rejecting loading gates, fake telemetry and game-like onboarding. Editorial accepted the criticism that its atmosphere alone would not demonstrate science, and rebuilt the local guide around actual processing and setup.

Root selected Living Atlas as one coherent world, with the product designer's record-sheet rigor and the immersive designer's continuity as functional requirements rather than competing palettes. The root did not stage a fake unanimous live conversation; these were written proposals, exchanged critiques and explicit votes. An initial account usage limit interrupted the agents; they resumed after the user's instruction to continue.

## Implemented

Pale mineral hero, expressive Newsreader type, natural Earth lighting, a thin orbit and geographic grid, compact glass question control, new working question index, short editorial method spread, complete case-file evidence sheet, redesigned scenario sheet, and a rebuilt AirLLM local field guide. DigiTwin retains its reversible roll and distinct simulated identity. One renderer and demand-based scheduling remain intact; no backend modifications.

## Verification

`npm test`: 9 passed. TypeScript/Vite build passed. Desktop and 390px screenshot inspected, AirLLM route inspected, mode change retained the same canvas, paused600ms sample drew zero frames, and browser reported no horizontal overflow. Impeccable source scan reported no deterministic findings in the new sources (source-only scan, not full accessibility certification). Actual font loading confirmed DM Sans and Newsreader. Main runtime still lacks /api/twin; capability state is honest and no results are fabricated.

Proposals: 01-immersive.md, 02-editorial.md, 03-product.md; product rebuttal in 04-debate.md, other critiques in respective proposals. Current original automatic design gate remains unavailable as recorded in frontend/VERIFICATION.md; no passing gate is claimed.
