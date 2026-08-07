## 2026-08-07 - Add tooltips to disabled operator actions
**Learning:** Native `title` attributes on disabled buttons do not display because they don't capture pointer events in most major browsers.
**Action:** Use a wrapper element (like a `span` or `div`) around the disabled button to attach the `title` attribute, ensuring keyboard accessibility by dynamically toggling `tabindex` on the wrapper only when the button is disabled.
