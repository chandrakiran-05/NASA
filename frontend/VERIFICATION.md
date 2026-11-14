# Redesign verification

Checked 15 November 2026 against the approved centered Earth / DigiTwin design.

## Passing checks

- `npm test`: 9 frontend tests passed. Covers prompt topic/location interpretation, continent navigation boundaries, exact DigiTwin request shapes, ID/numeric validation, capability errors and cancellation.
- `npm run build`: TypeScript and Vite production build passed. npm dependency audit reported zero vulnerabilities at installation.
- Existing `tests/test_twin.py` from an isolated archive of exact backend branch `ecf2892`: 5 passed in 15.62s. The main working tree's backend was not changed or switched. One existing Starlette/httpx deprecation warning.
- Browser: typing temperature in India resolves the region before submission. Twin rainfall in Africa selects a navigation view; returning restores observed India, its question, and temperature topic.
- One canvas remains identical across observed/Twin transitions. The changed heading, palette, route and prompt mode are visible; the current main server's 404 produces a capability message instead of fake results.
- Paused rendering is zero over both 1000ms and 600ms samples; keyboard rotation still invalidates and draws. Offscreen rendering is zero. Last RAF median sample: 16.6ms. Idle globe sample: 25 renders/sec within a 30fps budget, DPR 1.25.
- Desktop and 390px mobile renders inspected. Mobile composition was adjusted so the headline remains visible around Earth and prompt controls fit.
- `git diff --check` passed. `git diff --quiet -- backend tests scripts` returned zero: backend sources/tests/scripts unchanged.
- Impeccable source detector reported no deterministic findings in the redesigned CSS, App, Globe or TwinLab. This is a source-only scan, not a full accessibility certification. DESIGN.md now documents the intentional fonts; temporary font ignores were removed. The prior decorative CSS grid was removed; the requested geographic grid belongs to the globe.

## Performance comparison

Before: ~183 draw calls/sec visible, ~171 paused, ~183 offscreen. The original 1075×748 CSS canvas rendered at 1612×1122 pixels. After: paused/offscreen draw nothing and a comparable canvas is 950×662 pixels with capped DPR. This measures reduced work; it is not a promise for every device.

The lazy evidence-chart bundle fell from ~1.47 MB gzip to ~378 KB gzip using Plotly's official basic distribution. Vite still warns that its chart chunk exceeds 500 KB uncompressed; the hero does not load it.

## Limits

Live NASA/NOAA acquisition and actual local-LLM inference were not exercised. The running main backend uses deterministic fallback and lacks `/api/twin`; full twin API tests ran separately against the fetched branch archive. No public deployment was created.

The earlier design gate returned `GATE: ERROR` because its Chrome could not start. It was not rerun as a passing gate. Separate local screenshot/browser verification was used for this redesign.

## Living Atlas rebuild
Three research agents compared immersive, editorial and product directions and selected Living Atlas after written critiques. Sources, access limits, debate and validation: ../docs/design-research/05-decision-and-validation.md. Latest npm test: 9 passed. Latest production build passed. Desktop/mobile and AirLLM inspected, one canvas preserved through DigiTwin flip, settled pause drew 0 frames over 600ms. Backend unchanged. Current type system is Newsreader + DM Sans as documented in DESIGN.md.


## Goal audit additions
The globe now crosses the hero bottom; translucent title alpha is0.24. Twin roll and opposite-hemisphere turn both reach pi and reverse to0. Live existing-branch preview data upload/simulation and the500-run browser scenario flow passed. Preview5180 now uses isolated existing backend8001, so its twin capability is available. Full audit: ../docs/design-research/06-goal-completion-audit.md.

## 15 November refinement checkpoint

- Saved initial frontend to GitHub branch `frontend` as `eb2b734` before refinement.
- Current frontend suite: 15 tests pass, including six geographic cases checking that the selected point faces the camera and geographic north remains above it. TypeScript / Vite build passes.
- Globe uses explicit north-up latitude/longitude orientation and local-axis idle rotation. One enlarged canvas crosses the hero fold into reserved continuation space. Visible pause/reset box removed; focused globe supports Space to pause automatic rotation and Home to reset its orientation.
- Browser: India prompt, DigiTwin flip to approximately pi on both presentation axes, return to zero, and one canvas verified. Settled and offscreen render counts each remained unchanged over 650ms.
- Apple-inspired translucent prompt and star blue accents inspected on desktop and 390px mobile. Mobile hero subtitle moved into clear space above Earth. AirLLM mobile also inspected with reduced motion enabled through the screenshot browser.
- AirLLM flow animation runs when visible, pauses via its control, and pauses offscreen while the visible layer-loading illustration runs. Hidden-document support and reduced-motion rules are present; continuous illustrations explicitly say they are illustrated processing flow.
- BEAST, checked local-model reasoning, and optional AirLLM review descriptions checked against existing backend branches. No backend code or endpoint changes.
- Font findings addressed by replacing the undeclared Manrope heading declaration with documented Newsreader. DM Sans remains documented. No new suppressions added.
- Remaining build advisory: the lazy Plotly evidence chart is above Vite's 500KB uncompressed chunk threshold. External NASA/NOAA acquisition and actual model inference were not rerun for these frontend refinements.

## Conversation and focus verification

- 25 automated tests pass: prompt interpretation, geographic orientation under observed/partial/twin rolls, surface ribbons at the date line, actual country aliases and continent grouping, cached asset cancellation, bounded conversational context, and twin API contracts.
- Dedicated local browser run passed (frontend/shots/conversation-qa.json, ignored QA artifact): India has 810 boundary vertices and its marker is 148px above the desktop prompt; Africa has 13,446 vertices and a centered target in DigiTwin.
- Cinematic intermediate roll 0.259 radians and camera distance 3.325, final roll pi / Y turn zero / distance 3.850. Same canvas preserved.
- At 390px, headline bottom247.78 and subtitle top263: no collision. No horizontal overflow at390 or320. Viewport screenshots inspected for observed/Twin/chat; the headless stitched screenshot is not used as evidence of fixed positioning.
- Native shared-composer transition invoked once. Real backend initial answer and follow-up produced four transcript turns, correctly labeled deterministic. The globe stopped rendering behind chat. A temporary browser-only503 injection exposed retry; restoring the original fetch completed the answer. A temporary pending request was canceled and produced the stopped state. Production request behavior was restored.
- Reduced motion immediately returned roll to0 and disabled ambient animation. Settled rendering count was unchanged over500ms. Desktop browser also confirmed scene scroll offset and changing ambient transforms.
- Source detector reported no deterministic design findings. Existing lazy chart bundle size advisory remains. No backend endpoint or source changes. Actual local-model inference and fresh upstream NASA/NOAA acquisition were not exercised.
