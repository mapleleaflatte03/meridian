## 2026-05-30 - Focus visible and Disabled UX States
**Learning:** Adding `:disabled` CSS states natively using `pointer-events: none` prevents the browser from showing `cursor: not-allowed`, degrading the UX. We need to use `opacity: 0.5` combined with `cursor: not-allowed` without `pointer-events: none`.
**Action:** When adding `:disabled` UX states to buttons, always ensure `pointer-events` remain enabled if `cursor: not-allowed` is desired.
