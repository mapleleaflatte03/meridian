## 2026-07-03 - Global focus-visible border-radius
**Learning:** When adding global `:focus-visible` outline styles in CSS, avoid setting a `border-radius` property. Modern browsers natively curve the outline to match the element's existing border-radius; explicitly setting it globally overrides specific element shapes, causing visual regressions.
**Action:** Always omit `border-radius` when defining global `:focus-visible` outline styles, allowing the browser to natively inherit the curve from the active element.
