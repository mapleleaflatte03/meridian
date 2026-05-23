## 2024-05-23 - Visual Feedback for Disabled Operator Actions
**Learning:** The bulk action buttons (`.operator-action`) on the Trust Ops page were functionally disabled but visually indistinguishable from active buttons, causing potential user confusion.
**Action:** Added CSS rules for `.operator-action:disabled` to lower opacity (0.4) and provided a hover background color for enabled buttons, making it clear which elements are interactive vs inactive without screen reader reliance.
