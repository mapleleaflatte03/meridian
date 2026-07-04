## 2026-07-04 - Avoid border-radius on global :focus-visible
**Learning:** When adding global `:focus-visible` outline styles in CSS, explicitly setting `border-radius: inherit;` overrides the element's specific shape, causing visual regressions (like snapping round objects to squares). Modern browsers natively curve the outline to match the element's existing border-radius.
**Action:** Do not set a `border-radius` property in global `:focus-visible` selectors; let the browser automatically match the element's curve.
