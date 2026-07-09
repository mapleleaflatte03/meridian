## 2026-07-09 - Global focus-visible indicator
**Learning:** Many interactive elements (buttons, inputs, links) lacked a clear focus indicator. A global `:focus-visible` outline is critical for keyboard navigation accessibility without breaking mouse click aesthetics.
**Action:** Added a global `*:focus-visible` rule in the CSS to apply an outline. Always ensure a global focus outline exists in any new project, using `:focus-visible` to restrict it to keyboard interactions.
