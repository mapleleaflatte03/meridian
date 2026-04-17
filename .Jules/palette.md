## 2024-05-17 - Dynamic status elements lack aria-live attribute
**Learning:** Found that dynamic status indicators (`.operator-status` displaying async sync/auth status) in the Trust Ops dashboard do not use `aria-live="polite"`. Without this, screen readers will not announce when the status updates dynamically (e.g. "Trust Ops sync initialized.", "Operator token required.").
**Action:** Add `aria-live="polite"` and `aria-atomic="true"` to dynamic `.operator-status` paragraphs to make status changes accessible to screen readers, adhering to proper a11y patterns.
