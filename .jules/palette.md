## 2026-07-15 - Global Focus Visible Styling

**Learning:** Global focus states are missing in the CSS, limiting keyboard navigation visibility across buttons, links, and forms.
**Action:** Adding `:focus-visible` with a 2px solid `var(--accent)` border and `outline-offset: 2px` creates a consistent, distinct visual indication for all focusable elements without relying on mouse hover, dramatically improving a11y for keyboard navigation.
