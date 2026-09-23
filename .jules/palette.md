## 2026-04-18 - Dynamically clearing static disabled explanations
**Learning:** When adding static `aria-label` or `title` attributes to explain why an element is disabled (e.g. "Select items first"), if that element can be dynamically enabled by JavaScript, the static explanations will persist and override the normal accessible name.
**Action:** Always ensure the JavaScript that enables the element also explicitly removes or resets the `aria-label` and `title` attributes.
