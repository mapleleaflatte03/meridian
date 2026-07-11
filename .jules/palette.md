## 2026-07-11 - Global focus-visible styles missing
**Learning:** The application lacked a global focus-visible outline for keyboard users, relying only on default browser outlines (or no outline at all) which can be hard to see against the dark background.
**Action:** Added a global `:focus-visible` rule in `meridian.css` using the `--accent` design token to ensure high visibility and a consistent keyboard navigation experience across all interactive elements.
