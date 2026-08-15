## 2026-08-15 - Dynamic Tooltips for Disabled Buttons
**Learning:** When adding wrapper elements to provide tooltips for disabled buttons, hardcoding `tabindex="0"` creates an accessibility regression where keyboard users hit confusing double tab stops once the button is dynamically enabled by JavaScript.
**Action:** Dynamically remove the `tabindex` and `title` attributes from the tooltip wrapper when the JavaScript enables the nested button.
