## 2024-05-30 - Focus Indicators and Disabled States
**Learning:** Interactive elements globally lacked focus-visible indicators, making keyboard navigation nearly impossible, and disabled bulk actions in the Trust Ops queue lacked both visual disabled styling and screen reader context for why they were disabled.
**Action:** Added global `:focus-visible` styles for a11y, unified `:disabled` button states (opacity, cursor), and used `aria-label="[Action]: [Reason]"` pattern for disabled buttons to maintain accessible name while providing context.
