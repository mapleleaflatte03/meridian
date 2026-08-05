## 2024-08-05 - Tooltips for disabled buttons

**Learning:** When using wrapper elements to provide tooltips for disabled buttons, adding `tabindex="0"` to the wrapper breaks accessibility if the button's disabled state is dynamically toggled by JavaScript. The user will encounter confusing double tab stops when the button is enabled. Additionally, native title attributes do not work on disabled buttons as they don't capture pointer events.

**Action:** Ensure that if a wrapper is used with `tabindex="0"`, the `tabindex` is dynamically toggled so it's only present when the button is disabled, or just omit `tabindex="0"` on the wrapper entirely if tab order is already sufficient, or dynamically add/remove it in JS.
