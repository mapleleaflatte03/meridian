## 2024-05-20 - Global Focus Styles
**Learning:** When adding global `:focus-visible` outline styles in CSS, modern browsers natively curve the outline to match the element's existing border-radius. Explicitly setting a global border-radius overrides specific element shapes, causing visual regressions (like snapping round objects to squares).
**Action:** Avoid setting a `border-radius` property when defining global `:focus-visible` outline styles.
