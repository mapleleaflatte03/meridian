## 2026-08-16 - Add Tooltips to Disabled Buttons
**Learning:** Native `title` attributes and keyboard focus on disabled `<button>` elements are dropped by most browsers. Using a focusable wrapper element dynamically manages this accessibility gap.
**Action:** Always wrap dynamically disabled buttons in a `<span>` with a `title` and toggle `tabindex="0"`, making sure to remove them when the button is enabled to prevent confusing double tab stops.
