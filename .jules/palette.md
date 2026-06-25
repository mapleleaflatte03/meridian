## 2024-06-25 - Added Global :focus-visible Outline
**Learning:** Found that keyboard navigation across the entire public surface (e.g. `intelligence/company/www/*`) lacked a clear focus state for interactive elements except for a few specific inputs. Relying on default browser focus rings is inconsistent, especially on dark themes.
**Action:** Implemented a global `:focus-visible` rule in `meridian.css` using the existing `--accent` CSS variable to ensure robust, theme-aware keyboard accessibility on all buttons, links, and focusable items, providing a consistent and deliberate UX.
