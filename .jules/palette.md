## 2026-08-06 - Tooltips on disabled buttons
**Learning:** Native `title` attributes do not display on `disabled` HTML elements (e.g., `<button disabled>`) because they do not capture pointer events in most major browsers.
**Action:** Use wrapper elements around disabled buttons to provide tooltips and accessibility, ensuring to dynamically remove `tabindex` and `title` when the button is enabled to prevent confusing double tab stops for keyboard users.
