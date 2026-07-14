## 2026-07-14 - Keyboard Navigation Visibility
**Learning:** Found that focus-visible styles were missing across the Meridian CSS framework, causing poor keyboard navigation accessibility for interactive elements like buttons and links.
**Action:** Added global :focus-visible rules to meridian.css to ensure that keyboard focus is explicitly visible using outline and outline-offset properties. (Avoiding inherit on border-radius based on memory constraints)
