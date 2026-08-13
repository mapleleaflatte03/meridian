## 2026-08-13 - Add tooltip wrapper to disabled buttons
**Learning:** Native `title` attributes do not display on disabled HTML elements (`<button disabled>`) because they don't capture pointer events in most major browsers.
**Action:** Always wrap disabled elements with a `span` or `div` (e.g. `operator-action-wrapper`) that handles the `title` attribute and pointer events, and dynamically remove `title` and `tabindex` when the button is enabled to prevent accessibility regressions.
