# Product: Earth System Trend Detective

## Audience and purpose

Students, educators and scientifically curious people investigate regional Earth-system change. A natural-language question becomes an official time series, statistical evidence and a traceable explanation. This is an independent NASA Space Apps hackathon project, not a NASA-operated service.

## Main tasks

Select an Earth-science variable, place and period; acquire NASA/NOAA observations through the backend; visualize their time series; inspect rate, uncertainty, significance, integrity and provenance. Users may upload monthly CSV instead of acquiring new upstream data. No statistics are computed in the browser.

DigiTwin is a separate scenario sandbox: select/create a twin; upload research data or deliberately copy an observed record; confirm numeric assumptions; compare simulated outcomes and a simulated reference. Its actual backend exists on backend-active-trends, separate from the current main runtime. Current main returns404; unavailable handling is intentional, not a fake result.

## Experience commitments

Centered realistic interactive 3D Earth with geographic grid; prompt-driven place focus and labeled topic cues; compact glass prompt; reversible upside-down DigiTwin transition using the same renderer; observed and scenario states remain separate. Small NASA mark, Features and Try AirLLM navigation. Minimal useful story below the hero; consistent evidence, twin and AirLLM surfaces.

## Scientific trust

All scientific values and tests come from backend responses. Missing observations remain gaps. Date and units accompany observations; historical monthly values are not live weather. Simulations, reference curves and threshold probabilities are always identified as simulated. Show disclaimers/caveats; keep provenance reachable. Model text is text, never HTML. Credentials stay server-side.

## Technical boundaries

React/TypeScript/Vite with one optimized Three.js scene. Capped adaptive DPR, no rendering offscreen/hidden/settled-paused. Lazy charts. No backend changes, endpoint creation or branch merge in this task. Exact contracts are in docs/AGENT-DESIGN-BRIEF.md and branch backend-active-trends ecf2892.

## Current redesign authority

The user requested a complete aesthetic rebuild and explicitly delegated new concepts, research, debate and selection to subagents. Preserve prior functional commitments, replace the visual composition across all routes. Research accessible Awwwards and other showcases for principles, never copy their code or proprietary art.
