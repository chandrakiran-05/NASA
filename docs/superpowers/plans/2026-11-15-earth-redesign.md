# Earth redesign implementation plan

> For agentic workers: use subagent-driven development for independent components and inline integration.

**Goal:** Deliver the approved centered, responsive Earth interface and reversible DigiTwin mode with less rendering work.

**Architecture:** Keep one persistent globe. Root owns app composition, topic/location state, CSS and observed evidence integration. Bounded agents own Globe and Twin controls/API respectively. Preserve backend source and runtime branch.

**Tech stack:** React, TypeScript, Vite, Three.js; lazy Plotly for results only.

**Spec:** `docs/superpowers/specs/2026-11-15-earth-redesign.md` (user approved).

## Global constraints

- No backend, tests/ or scripts/ changes; no backend endpoint creation or merge.
- Use actual `/api/twin` contract from ecf2892; handle missing capability on current main.
- One renderer across modes. Never label simulation as observation.
- Keep accessible controls, reduced motion, all scientific units/disclaimers.

## Review focus

- Rapid mode toggles reverse without remounting or a stale simulation writing into observed state.
- Debounced region lookup ignores superseded network responses.
- Missing twin route reports the connection state without substituting another model.
- Paused/offscreen Earth stops drawing; input and focus changes still invalidate it.
- Small screens preserve type legibility, prompt access and scrolling around globe drag.

## Tasks

- [ ] 1. Replace Globe.tsx rendering scheduler, add twin/topic props, pointer drag and grid. Verify draw calls visible/paused/offscreen and identity across mode changes.
- [ ] 2. Add twinApi.ts and TwinLab.tsx with real existing twin selection, CSV/import and explicit scenario controls. Expose imperative `submitPrompt(question)` for the hero and a readable progress/error surface. Mock-check request shapes and 404 behavior.
- [ ] 3. Recompose App hero, isolate existing evidence view, implement debounced prompt geography/topic reactions and mode routing. Keep observed results across mode transitions. Add tests for pure keyword interpretation where meaningful.
- [ ] 4. Replace page CSS and DESIGN.md with approved Earth system, reduced glass cost, compact narrative, pointer lighting. Preserve AirLLM styling, clarify newer-branch support.
- [ ] 5. Build, verify API boundaries, inspect responsive renders, compare performance probes, review all changes and document connection limits. Do not commit or publish unless requested.
