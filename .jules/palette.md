## 2026-07-08 - Global Focus Visible Outline
**Learning:** Adding a global *:focus-visible outline ensures keyboard accessibility for all interactive elements, but using `border-radius: inherit;` inside it strips the default curvature of elements, causing significant visual regressions.
**Action:** Always provide a clear outline for *:focus-visible without forcing inheritance of properties like border-radius that could break the component's established design constraints.
