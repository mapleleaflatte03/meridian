## 2026-09-09 - Tooltip for disabled buttons
**Learning:** Adding a tooltip to a disabled HTML element requires wrapping the element in a container (like a `span`), setting `pointer-events: none` on the disabled element, and applying the `title` and `cursor: not-allowed` properties to the wrapper. This is because disabled elements often ignore mouse events.
**Action:** When adding tooltips to disabled elements, always wrap them and adjust pointer events. Remember to reverse these properties (e.g., `pointer-events: auto`, remove `title`) when dynamically re-enabling the element via JavaScript.
