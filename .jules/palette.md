## 2026-04-18 - Global Focus-Visible Border Radius
**Learning:** Modern browsers natively curve the :focus-visible outline to match an element's existing border-radius. Setting a global border-radius overrides this behavior, causing visual regressions like snapping round objects to squares.
**Action:** Avoid setting border-radius on global :focus-visible rules; only use outline and outline-offset.
