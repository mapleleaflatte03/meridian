## 2026-07-16 - Focus Indicators and Border Radius
**Learning:** Using \`border-radius: inherit;\` inside global \`:focus-visible\` rules is dangerous. It forces the element to inherit border-radius from its parent, stripping native element curvature and causing visual regressions.
**Action:** Exclude \`border-radius: inherit;\` from global focus resets and instead rely on native element outlines or explicitly mapped variables to preserve intended component shapes during keyboard navigation.
