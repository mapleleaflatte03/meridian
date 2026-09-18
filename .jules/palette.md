## 2026-04-18 - Tooltips on disabled buttons in Flexbox
**Learning:** Wrapping disabled elements in container spans to apply hover tooltips breaks the UI layout when the elements are styled as direct children in flexbox or grid layouts (e.g. `.operator-actions > button`). Adding `aria-label` and `title` directly to the disabled elements and dynamically toggling them via JS is necessary.
**Action:** When adding tooltips to disabled elements in flexbox/grid layouts, apply ARIA labels and titles directly instead of using a wrapper element to avoid layout breakage.
