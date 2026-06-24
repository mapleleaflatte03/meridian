## 2026-06-24 - Native Border-Radius with Global Focus Visible Styles
**Learning:** When adding a global `:focus-visible` outline in CSS, explicitly setting a `border-radius` property overrides specific element shapes, causing visual regressions (like snapping round objects to squares). Modern browsers natively curve the outline to match the element's existing border-radius.
**Action:** Always avoid setting `border-radius` on global focus outlines. Use `outline` and `outline-offset` to provide clear keyboard focus indicators while respecting the native curves of components.
