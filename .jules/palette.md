## 2026-08-27 - Added tooltips to disabled bulk action buttons
**Learning:** Adding the `title` attribute directly to disabled HTML buttons is sufficient for tooltips and avoids tab-index bugs and styling issues associated with JS wrappers.
**Action:** Use native HTML `title` attributes for simple tooltips on disabled elements where appropriate.
