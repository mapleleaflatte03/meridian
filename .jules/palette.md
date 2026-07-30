## 2024-05-24 - Missing ARIA current state on active navigation links
**Learning:** The site navigation highlights the active page visually using `class="current"`, but fails to convey this state to assistive technologies.
**Action:** Always add `aria-current="page"` alongside visual active state classes in navigation menus to ensure screen reader users can identify their current location.
