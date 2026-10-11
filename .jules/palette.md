## 2024-05-24 - Do not use pointer-events: none; on disabled elements

**Learning:** When styling disabled elements in CSS, applying `pointer-events: none;` prevents native browser tooltips (like the `title` attribute) from rendering across modern browsers. This breaks accessibility for users trying to understand why an action is disabled.

**Action:** Add static `aria-label` or `title` attributes that explain disabled states, but avoid applying `pointer-events: none;` on disabled elements. Ensure any JavaScript dynamically updating the disabled state also resets the tooltip.
