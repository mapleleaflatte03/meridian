## 2026-09-16 - Add disabled state styling for Operator actions
**Learning:** The operator bulk actions in the Trust Ops UI have `disabled` attributes when no items are selected, but they lack distinct disabled styling in CSS, meaning they look identical to interactive buttons, causing UX confusion.
**Action:** Always verify that actionable elements with a `disabled` attribute have a visually distinct state (e.g. reduced opacity, `cursor: not-allowed`). Add `:disabled` rules for UI components in this app's design system when they are missing.
