## 2026-08-31 - Disabled button tooltips
**Learning:** Disabled buttons in WebKit/Blink browsers do not fire mouse events, meaning tooltips (the `title` attribute) will not appear on them.
**Action:** Wrap the disabled element in a span container with `cursor: not-allowed` and `tabindex="0"`, set `pointer-events: none` on the disabled button itself, and put the `title` on the wrapper. Use JS to toggle these attributes when the button becomes enabled/disabled.
