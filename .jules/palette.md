## 2023-10-27 - Disabled State Tooltips
**Learning:** When adding tooltips or accessible explanations to disabled buttons, modifying the `aria-label` completely replaces the accessible name for screen readers. It's crucial to preserve the original button text within the new `aria-label` (e.g., `aria-label="Approve: Select items first"`) or use `aria-describedby` to avoid accessibility regressions where the element's identity is lost.
**Action:** Always include the primary action text when modifying `aria-label` for disabled states, or prefer `aria-describedby` when possible.
