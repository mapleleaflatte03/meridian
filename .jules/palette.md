## 2026-07-01 - Global focus-visible border-radius
**Learning:** In CSS, `border-radius: inherit;` does not mean 'keep the element's default state'; it explicitly forces the element to inherit the `border-radius` from its parent container. Using `border-radius: inherit;` inside global `:focus-visible` rules causes major visual regressions by stripping native curvature from elements.
**Action:** When adding global `:focus-visible` outline styles, avoid setting a `border-radius` property and allow modern browsers to natively curve the outline.
