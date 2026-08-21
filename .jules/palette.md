## 2026-08-21 - Tooltips on Disabled Buttons

**Learning:** When adding tooltips to disabled elements, adding the `title` attribute directly to the disabled HTML button is often sufficient and avoids the tab-index accessibility bugs and styling issues associated with JS-managed tooltip wrappers.

**Action:** Add the `title` attribute directly to disabled buttons and dynamically manage its presence via JS to ensure screen readers or visual users get helpful context without breaking tab order.
