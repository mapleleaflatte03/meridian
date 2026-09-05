## 2026-09-05 - Tooltips on disabled buttons
**Learning:** Disabled elements don't fire mouse events, meaning standard HTML tooltips (title) don't work. When adding tooltips to disabled buttons while strictly adhering to a "no custom CSS" constraint, they must be wrapped in a `span` with inline styles (`cursor: not-allowed`).
**Action:** Ensure the wrapper handles the hover events and dynamically toggle both the wrapper's `title`/`cursor` and the button's `pointer-events` via JavaScript when the disabled state changes.
