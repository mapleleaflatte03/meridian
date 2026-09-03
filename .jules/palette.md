## 2026-09-03 - Tooltips on disabled elements
**Learning:** Adding tooltips (like `title`) directly to `disabled` buttons doesn't work consistently because disabled elements don't fire mouse events.
**Action:** Always wrap disabled elements in a container (like `span`) with `pointer-events: none` on the inner element and apply the `title` and `cursor: not-allowed` properties to the wrapper. Dynamically remove these styles when the element is enabled.
