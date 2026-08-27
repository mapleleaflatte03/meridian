## 2026-08-27 - Disabled Button Tooltips Browser Bug
**Learning:** Adding the `title` attribute directly to disabled HTML buttons fails in WebKit/Blink browsers because disabled form elements do not fire mouse events (like hover).
**Action:** Wrap disabled buttons in a container (like a `span`), set `pointer-events: none` on the disabled element via CSS, and apply the `title` and `cursor: not-allowed` properties to the wrapper.
