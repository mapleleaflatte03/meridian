## 2026-04-18 - Tooltips on disabled buttons
**Learning:** When styling disabled elements, using `pointer-events: none` prevents native browser tooltips (`title` attributes) from working, reducing accessibility for users who need to know *why* a button is disabled.
**Action:** Do not use `pointer-events: none` on disabled buttons if they need to provide a tooltip explanation. Handle disabled states using `:disabled` pseudo-class without preventing pointer events, or use visually hidden alternative text.
