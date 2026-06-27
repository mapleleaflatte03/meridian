## 2026-06-27 - Global focus-visible styles
**Learning:** When adding global `:focus-visible` outline styles in CSS, avoid setting a `border-radius` property. Modern browsers natively curve the outline to match the element's existing border-radius; explicitly setting it globally overrides specific element shapes, causing visual regressions.
**Action:** Use `outline` and `outline-offset` without `border-radius` for global focus styles.
