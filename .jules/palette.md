## 2024-06-06 - Concise Navigation Announcements
**Learning:** While icon-only links containing images with descriptive `alt` attributes are technically accessible, explicitly setting an `aria-label` on the parent `<a>` tag overrides potentially verbose image `alt` text (like our logo's multi-word tagline).
**Action:** Use `aria-label` on parent anchor tags to provide a concise navigation announcement (e.g., 'Meridian Home') for icon-only brand links.
