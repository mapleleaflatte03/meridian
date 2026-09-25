## 2026-09-25 - Disabled button feedback
**Learning:** Adding standard visual cues (opacity and tooltips) to disabled buttons without using `pointer-events: none` preserves native browser tooltips and improves accessibility by explicitly explaining why the button is unavailable.
**Action:** When adding static aria-label attributes or titles to explain disabled states dynamically updated via JS, update the JS to remove or reset the label when the element becomes active.
