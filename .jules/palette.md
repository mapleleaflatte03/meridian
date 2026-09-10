## 2024-04-18 - Added tooltips to disabled bulk action buttons
**Learning:** When using standard `disabled` attributes on HTML buttons, standard browser behavior prevents pointer events and suppresses the `title` tooltip, making it impossible to communicate *why* a button is disabled to mouse/keyboard users.
**Action:** Wrap disabled interactive elements in a non-interactive span with the `title` attribute and `cursor: not-allowed`, while explicitly adding `pointer-events: none` to the child button. Restore native pointer behavior dynamically when re-enabling.
