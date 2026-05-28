## 2026-05-28 - Add accessible disabled and focus-visible states
**Learning:** Found that custom buttons (`.cta`, `.operator-action`) and standard form elements lacked global `:focus-visible` states and explicit disabled visual cues. Since `pointer-events: none` suppresses standard cursors, it's better to use `opacity` and `cursor: not-allowed` on the base element.
**Action:** Next time designing interactive elements, ensure focus and disabled states are part of the baseline reset.
