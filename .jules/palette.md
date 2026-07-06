## 2026-07-06 - Global Focus Styles

**Learning:** When implementing global `:focus-visible` styles to improve keyboard accessibility, relying on `outline` with `outline-offset` provides a consistent and visually distinct focus indicator without overriding individual element border radii. Avoid using `border-radius: inherit;` inside global `:focus-visible` rules to try and preserve native curvature, as it explicitly forces inheritance from the parent container and strips specific element styling, causing major visual regressions.
**Action:** Always use `outline` and `outline-offset` for global focus states rather than trying to match border-radius globally, and verify focus styles by navigating via the 'Tab' key with a screen reader or automated test script.
