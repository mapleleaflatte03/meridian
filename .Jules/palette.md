## 2024-05-09 - Added Tooltip for Disabled Action Buttons
**Learning:** Found that disabled bulk action buttons in the Trust Ops UI lacked explanatory feedback, which can be frustrating for screen reader users and sighted users alike when they do not understand why an action is unavailable. Native HTML `title` attributes can provide this feedback accessibly without needing to change any custom CSS classes.
**Action:** Used the native HTML `title` attribute dynamically toggled in JS to add tooltips that explain why buttons are disabled and what actions they perform when enabled.
