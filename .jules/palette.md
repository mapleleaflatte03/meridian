## 2026-06-28 - Missing global focus-visible styles
**Learning:** Found that the only focus styles in the entire app's CSS were limited to `.intake-field input` and `textarea`. Interactive elements like links (`<a>`) and buttons (`<button>`) are missing visual focus indicators for keyboard navigation, making the site difficult to use for keyboard-only users and failing WCAG 2.1 Success Criterion 2.4.7 Focus Visible.
**Action:** Add a global `:focus-visible` outline style to improve accessibility without breaking the existing design system or affecting mouse users.
