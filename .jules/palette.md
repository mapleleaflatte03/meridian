## 2026-09-04 - Tooltips on disabled elements
**Learning:** Tooltips do not work on disabled buttons directly. In `trust-ops.html`, the bulk action buttons are disabled when no items are selected, meaning they don't show tooltips natively, which can leave operators guessing why they are disabled.
**Action:** When adding tooltips to disabled HTML elements, wrap the element in a container (like a `span`), set `pointer-events: none` on the disabled element, and apply the `title` and `cursor: not-allowed` properties to the wrapper. Dynamically re-enabling requires reversing these styles in JS.
