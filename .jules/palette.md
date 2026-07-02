## 2026-07-02 - Avoid overriding border-radius in focus outlines
**Learning:** When adding global `:focus-visible` outline styles, setting `border-radius: inherit;` strips native browser heuristics for outline curvature, leading to visual regressions.
**Action:** Avoid explicitly setting `border-radius` inside global `:focus-visible` rules, relying instead on the browser's native rounded outline behavior.
