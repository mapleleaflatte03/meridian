## 2024-06-12 - Global Focus Visible Outline
**Learning:** When adding global `:focus-visible` outline styles in CSS, setting a `border-radius` property overrides specific element shapes, causing visual regressions (like snapping round objects to squares) because modern browsers natively curve the outline to match the element's existing border-radius.
**Action:** Avoid setting a `border-radius` property when defining a global `:focus-visible` outline to ensure modern browsers can accurately inherit and apply native border-radius curves.
