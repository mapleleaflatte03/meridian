## 2026-06-29 - Improve Icon-only links accessibility
**Learning:** Icon-only links (like logos) often lack descriptive text for screen readers. Using `aria-label` provides a concise navigation announcement (e.g., 'Meridian Home') and is a UX best practice, especially since `alt` attributes inside these links may be empty or overly verbose.
**Action:** When inspecting navigation or headers, look for icon-only links and explicitly add `aria-label` if it's missing to improve screen reader accessibility.
