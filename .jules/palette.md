## 2024-05-19 - Adding Accessible Tooltips for Disabled States
**Learning:** When using aria-label to explain why an element (like a button) is disabled, the aria-label completely replaces the visible text content for screen readers. Thus, the label must include the original text (e.g., "approve: Select items first") so screen reader users don't lose the element's identity.
**Action:** When adding aria-labels to elements with visible text, ensure the original text is preserved in the label or use aria-describedby instead.
