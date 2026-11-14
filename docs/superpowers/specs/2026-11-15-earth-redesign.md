# Earth interface redesign

Software: an immersive Earth-system investigation interface for NASA Space Apps.

## Intent and authority

Implement the user's twelve redesign requirements. Preserve the functional observed-data evidence flow while replacing the presentation and removing unnecessary rendering work. Backend endpoints must not be created, changed, or merged by this task. The user explicitly requested brainstorming and UI/UX Pro Max guidance.

## Sources inspected

Refreshed GitHub branch snapshots on 15 November 2026 without changing the working tree:

- `main` and `frontend`: `b3835e4`, observed-series analysis and investigation.
- `backend-active-trends`: `ecf2892`, adds the actual separate digital-twin implementation and API, active-trend checks, expanded connectors, AirLLM deep review, and BEAST updates.
- `research-evidence`: `33deaba`, implemented literature evidence plus a separate round-two roadmap explicitly marked unimplemented.

Challenge: identify Earth-science variables, acquire regional records, visualize time series, measure change and test significance. Reference: https://www.spaceappschallenge.org/2026/challenges/earth-system-trend-detective/

## Visual design

Builder's choice: retain React, TypeScript, Vite and Three.js. A framework migration would not solve the measured render-loop waste. One persistent WebGL scene serves both modes.

Observed world: near-black blue ground, ice cyan and pale mint, with restrained coral/amber accents. DigiTwin: deep warm plum-black ground, soft rose, peach and champagne light. No full-screen blur on the continuously moving Earth. Real textured imagery remains visible.

Header: small NASA mark and project identity at left. Only Features and Try AirLLM at right. Remove Heat explorer and The project links. Small-screen navigation remains accessible.

Hero: center a complete globe at desktop and mobile sizes. Put oversized live text behind the sphere, visible around its silhouette. Keep accessible full text in the heading. Replace the current left-aligned marketing layout.

- Observed heading: **Earth is changing.**
- Observed subline: **Investigate regional change with NASA data and test whether the trend holds up.**
- Twin heading: **A possible Earth.**
- Twin subline: **Explore how your assumptions change the outcome.**
- Persistent twin status: **Scenario sandbox · simulated results**.

The title is stationary behind the sphere with a restrained entrance; it must remain readable. Globe rotation provides the movement. Pointer movement adds a very small lighting/ground displacement; no replacement cursor, trailing particles, or React updates on every pointer event.

Prompt: a compact transparent pill near the bottom of the hero, a visible compact label, one-to-two-line input, and a round send button with a 44px effective target. The DigiTwin entry button sits directly underneath. Status/error/response expands only when needed.

## Globe behavior

- Real texture, thin atmosphere, a low-opacity latitude/longitude grid, and one marker for the selected region.
- Drag rotates the sphere; provide keyboard rotate/reset alternatives and pause control.
- Recognized words such as India, Africa, Tamil Nadu and Chennai focus the matching place before submission, after a short debounce. Use the backend region service for recognized regions; if continental names are unsupported, documented approximate geographic centers are only navigation aids, never scientific bounding boxes.
- Temperature, rain, vegetation and weather words select a clearly labeled visual topic accent. These are interaction cues, not measured heat maps. Only API-supplied values may be displayed as observations.
- On submit, observed mode follows the existing backend planning/investigation/evidence flow.
- Historical temperature readouts always include their actual month, variable and units. Do not present monthly history as live weather.
- DigiTwin entry rolls the same globe 180 degrees over approximately 1 second while text and ground crossfade. Blur only the small text layer briefly. The globe is never unmounted or hidden.
- DigiTwin prompt includes **Return to observed Earth**. Returning reverses the animation and restores the prior observed question, location and results.
- Rapid toggles must reverse from the current pose, without snapping or resetting the renderer. Reduced motion uses a brief crossfade and final pose.

## Backend connection

Keep API calls in the typed client. Do not create endpoints or change backend files.

Observed mode uses the existing `/api/ai/plan`, `/api/investigate`, region search, uploaded-series analysis and evidence endpoints.

DigiTwin selects a distinct client mode and uses the contract already present on `backend-active-trends`:

- `GET /api/twin`: select an existing twin.
- `POST /api/twin`: create a named twin when explicitly requested from the UI.
- `GET /api/twin/{id}`: uploaded variables and baseline metadata.
- `POST /api/twin/{id}/data-csv` or `/data`: direct research data, kept separate from verified observations.
- `POST /api/twin/{id}/import`: deliberate one-way copy of an observed series.
- `POST /api/twin/{id}/simulate`: confirmed scenario settings.

There is no natural-language twin-planner endpoint. A prompt may identify a place and express intent, but must not silently invent scenario knobs. Show a compact editable scenario form for variable, horizon, trend multiplier/addition and optional threshold; offer advanced shock/driver fields if needed. Only send the displayed, user-confirmed settings. Default simulation size and seed can use backend defaults. Existing-twin data is never replaced implicitly.

Simulation results: show API-returned median and p05/p95 bands, optional simulated reference and `delta_p50`, threshold probability curve and actual response disclaimer. Preserve variable order because drivers may refer only to previously uploaded variables. Do not transform simulation output into verified observed evidence.

The current main-branch server may return 404 for `/api/twin`. Show **DigiTwin is not available on the connected backend** and retain the interface and setup explanation. Do not substitute `/api/insights` forecasts, invent data, switch branches, or merge the backend. Connecting the newer backend is a separate runtime decision.

## Below the hero

Observed mode: one compact section with three clear ideas—regional records, integrity checks, and statistical evidence—plus access to the existing evidence workspace and CSV upload. Remove the current long marketing sections.

Twin mode: one concise workflow section: research data → fitted baseline → scenario settings → simulated ranges. Show the real variable structure (`name`, `units`, `time`, `value`) and explain optional drivers and thresholds. Explain monthly climatology, linear trend and AR(1) noise without implying a physical global climate model.

Preserve AirLLM navigation; update its context to acknowledge actual AirLLM deep-review support exists on the newer backend branch, while the connected main backend may not expose it.

## Performance evidence and implementation targets

Before changes at 1280×613 and DPR 1.5: median RAF interval 16.7ms, p95 17ms, no frames above 32ms in a 120-frame sample. Severe user-reported lag was not reproduced on this machine.

Measured draw calls per second: visible 183, paused 171, offscreen 183. This confirms unnecessary rendering when motion should be idle. Current canvas is 1612×1122 pixels for a 1075×748 CSS area, with a 28px glass blur and three sphere passes.

Targets:

- No continuous draw calls when fully paused, offscreen or hidden; render only on invalidation.
- Idle rotation budget around 30fps, full refresh during gestures/transitions, adaptive DPR capped near 1.25 with a physical pixel ceiling.
- Lower sphere tessellation, combined grid geometry, one renderer, low-cost pointer effects and limited glass blur.
- No full Plotly download in the hero; load charts only on results and reduce its distribution if compatible with current charts.
- Preserve textures, layout stability, keyboard controls and reduced-motion support.

## Verification

Compare the same draw-call and frame-time probes before/after. Test both modes at 1440, 1024, 768, 390 and 320px; dragging, keyword focus, topic changes, pause, offscreen, reduced motion, repeated/reversed mode switching and browser back. Test observed API and exact twin payloads; exercise 404 capability handling on current main. Confirm no simulation is shown as an observation, all backend disclaimers remain accessible, and the production build passes.

## Explicit boundaries

No backend edits, no fabricated weather, no automatic simulation from unconfirmed natural language, no physical-planet forecasts, and no promises that unreleased research-roadmap features are implemented.
