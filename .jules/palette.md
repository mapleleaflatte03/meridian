## 2026-06-19 - Concise Navigation Announcements for Icon-Only Links
**Learning:** While icon-only links containing images with descriptive alt attributes are technically accessible, explicitly setting an aria-label on the parent <a> tag is a UX best practice to provide a concise navigation announcement (e.g., 'Meridian Home') and override potentially verbose image alt text.
**Action:** Always add an explicit aria-label to parent link tags when wrapping images that serve as primary navigation, even if the images have their own alt text.
