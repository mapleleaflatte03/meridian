## 2026-07-13 - Focus Styles and Outline Supression
**Learning:** The application was suppressing default browser outlines (`outline: none`) without providing a comprehensive `:focus-visible` fallback, breaking keyboard navigation visibility.
**Action:** Always provide a `:focus-visible` alternative (e.g., using a design-system-aligned accent color and `outline-offset`) whenever suppressing default outlines to ensure continuous keyboard accessibility.
