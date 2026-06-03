## 2026-06-03 - Added focus-visible styles globally
**Learning:** Adding `border-radius: 4px` inside a global `:focus-visible` rule is a CSS anti-pattern because it overrides the element's natural border radius, making perfectly round objects snap to squares on focus. Modern browsers natively curve outline to match an element's existing border-radius.
**Action:** Do not use `border-radius` with global outline fixes. Also, a single `:focus-visible` handles all types, redundant element targeting isn't needed.
