## 2026-09-07 - Disabled Action Button Tooltips
**Learning:** Native HTML `<button disabled>` prevents interaction, meaning tooltips added via the `title` attribute do not display on hover.
**Action:** When adding tooltips to disabled buttons, wrap the button in a `<span>` with `display: inline-block`, `cursor: not-allowed`, and apply the `title` to the wrapper while setting `pointer-events: none` on the button itself. Restore `pointer-events: auto` and clear the wrapper styles dynamically when the button state becomes active.
