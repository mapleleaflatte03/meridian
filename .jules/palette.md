## 2024-10-24 - Native Border-Radius on Focus Rings
**Learning:** When adding global `:focus-visible` outline styles in CSS, avoid setting a `border-radius` property. Modern browsers natively curve the outline to match the element's existing border-radius; explicitly setting it globally overrides specific element shapes, causing visual regressions (like snapping round objects to squares).
**Action:** Always omit `border-radius` from global `:focus-visible` definitions.

## 2024-10-24 - Accessible Icon-Only Link Announcements
**Learning:** While icon-only links containing images with descriptive `alt` attributes are technically accessible, explicitly setting an `aria-label` on the parent `<a>` tag is a UX best practice to provide a concise navigation announcement (e.g., 'Meridian Home') and override potentially verbose image `alt` text.
**Action:** Set concise `aria-label` attributes on parent `<a>` tags for icon-only links.
