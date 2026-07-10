## 2026-07-10 - Add global focus-visible state
**Learning:** The application lacked global `:focus-visible` states, completely breaking keyboard navigation accessibility because users could not see which element had focus.
**Action:** Always ensure a global `:focus-visible` rule is present (using a clear design token like `var(--accent)`) to provide visual feedback for keyboard users.
