## 2026-09-01 - Tooltips on Disabled Buttons
**Learning:** Native tooltips do not appear on disabled HTML elements in many contexts.
**Action:** Wrap disabled buttons in a container like a `span` with `pointer-events: none` on the button and `title`/`cursor` on the wrapper, restoring `pointer-events` dynamically when enabled.
