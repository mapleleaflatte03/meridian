## 2024-05-19 - Disabled Button States
**Learning:** Combining `pointer-events: none` with `cursor: not-allowed` on disabled states prevents the cursor from changing, and native tooltips don't reliably appear on disabled elements.
**Action:** Always use `cursor: not-allowed` and avoid `pointer-events: none` on disabled buttons if a tooltip or cursor change is desired.
