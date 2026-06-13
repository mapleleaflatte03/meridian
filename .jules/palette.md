## 2026-06-13 - Global Focus Indicators
**Learning:** The Meridian application completely lacked native focus rings for interactive elements, rendering keyboard navigation entirely invisible due to missing defaults in the base CSS.
**Action:** Always verify keyboard focus states globally early in a design system audit, and establish a global `:focus-visible` rule utilizing the brand `--accent` color to ensure a baseline accessible experience before refining individual component states.
