## 2026-07-17 - Focus Visible Border Radius Regression
**Learning:** Using `border-radius: inherit;` inside global `:focus-visible` rules causes major visual regressions by forcing elements to inherit the radius from their parent container, stripping their specific border-radius.
**Action:** Always omit `border-radius: inherit;` in global focus styles and rely on native outline rendering or specific component overrides instead.
