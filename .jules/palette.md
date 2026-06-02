## 2026-06-02 - Keyboard Accessibility for Call to Action
**Learning:** Custom interactive elements like `.cta` buttons and `.operator-action` links in the design system lack default browser focus rings when customized, leading to a critical WCAG 2.1 SC 2.4.7 failure.
**Action:** Ensure all custom interactive elements include explicit `:focus-visible` styles with sufficient contrast (e.g., using `var(--accent)`) during component creation, not as an afterthought.
