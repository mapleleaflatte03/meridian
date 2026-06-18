## 2024-10-24 - Missing Global Focus Indicators
**Learning:** The Meridian design system completely lacked global keyboard focus indicators (`:focus-visible`), causing a critical accessibility failure for keyboard-only users who couldn't track their navigation.
**Action:** Always verify global base CSS for `:focus-visible` rules, and inject a minimal, non-disruptive outline using existing design tokens (`var(--accent)`) rather than relying solely on element-specific focus states.
