1. **Explore the codebase and understand the task**
   - The task is to "find and implement ONE micro-UX improvement that makes the interface more intuitive, accessible, or pleasant to use".
   - The persona is "Palette" 🎨 - a UX-focused agent.
   - We must keep changes under 50 lines.
   - The app has a missing focus-visible outline on interactive elements like links and buttons. Adding a `focus-visible` rule in the global CSS improves keyboard accessibility significantly without affecting mouse users, which perfectly fits "Palette's" goals.

2. **Add focus-visible styles to the global CSS**
   - We have verified that `a` and `button` elements lack `:focus-visible` styling in `intelligence/company/www/assets/meridian.css`.
   - We have already appended the `:focus-visible` styles to `intelligence/company/www/assets/meridian.css` via a bash script:
     ```css
     a:focus-visible,
     button:focus-visible {
       outline: 2px solid var(--accent);
       outline-offset: 2px;
       border-radius: 2px;
     }
     ```

3. **Verify the change**
   - Run a quick text search to ensure `focus-visible` is in `meridian.css`.

4. **Update Palette's Journal**
   - Add a critical learning to `.jules/palette.md` noting the addition of global `focus-visible` to support keyboard navigation.
   - Use the format `## YYYY-MM-DD - [Title]\n**Learning:** [UX/a11y insight]\n**Action:** [How to apply next time]`.

5. **Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.**
   - Run formatting/linting scripts if available.
   - Run python unittests.
   - Review pre-commit instructions.

6. **Submit PR**
   - Create a PR with title "🎨 Palette: Add focus visible styles for keyboard navigation".
   - Include '💡 What', '🎯 Why', '📸 Before/After', and '♿ Accessibility' sections.
