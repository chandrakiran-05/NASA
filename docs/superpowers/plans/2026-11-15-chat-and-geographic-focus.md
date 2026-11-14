# Earth conversations and geographic focus

Software: refine Living Atlas in React, TypeScript and the existing Three.js scene.

1. Keep the chosen place facing the camera in both worlds; remove the opposite-hemisphere turn. Raise its visual target above the prompt. Draw actual navigation boundaries, with approximate labels for backend search extents and point markers for cities.
2. Keep one renderer. Change worlds through a 2.8-second close-up and upside-down roll; animate tint and interface color together. Reduced motion switches immediately.
3. Place the selected region above the glass prompt. Align the DigiTwin headline in intentional negative space. Refine type scale, control labels, consistent icon weight and brief hover responses. Add restrained moving light and scroll-linked Earth motion without scroll interception.
4. Hero submission enters /chat with a shared composer transition. Chat continues through the existing /ai/ask contract, retains its transcript in memory, offers cancellation, retry and exit, and identifies the actual response source. Keep data investigation available from each chat question; no backend changes.
5. Verify geographic math, boundary selection, bounded conversation context, normal and DigiTwin targeting, cinematic intermediate/end states, chat enter/continue/exit, errors, mobile layout, reduced motion, and offscreen rendering. Build and inspect desktop/mobile output before completion.

Ownership: globe agent owns globe math/scene; chat agent owns the chat surface; geography agent owns navigation assets/lookup; primary agent owns orchestration, visual refinement and browser validation.
