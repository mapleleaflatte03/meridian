## 2024-06-15 - Concise Navigation Announcements
**Learning:** While icon-only links containing images with descriptive `alt` attributes are technically accessible, explicitly setting an `aria-label` on the parent `<a>` tag is a UX best practice to provide a concise navigation announcement (e.g., 'Meridian Home') and override potentially verbose image `alt` text.
**Action:** Always add explicit, concise `aria-label` attributes to parent links for navigation elements to prioritize clean screen reader announcements over verbose inner image `alt` text.
