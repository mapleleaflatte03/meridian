## 2026-07-05 - Global Focus Visibility
**Learning:** The application lacked clear focus indicators for interactive elements across all pages, severely impacting keyboard navigation accessibility. Using `:focus-visible` provides clear outlines for keyboard users while maintaining the default appearance for mouse users.
**Action:** Implement global `:focus-visible` styles with sufficient contrast (`rgba(135,216,255,0.45)`) and avoid setting `border-radius: inherit` in global focus rules to prevent visual regressions by overriding native element shapes.
