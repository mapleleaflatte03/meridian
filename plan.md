1. **Add general focus-visible styles for accessibility**
   - In `intelligence/company/www/assets/meridian.css`, add a `:focus-visible` rule.
   - This ensures that interactive elements have a clear focus ring when navigated via keyboard, improving keyboard accessibility.
   - The focus ring will use `var(--accent)` for the outline color to match the design system.
   - Importantly, do NOT use `border-radius: inherit;` as it causes visual regressions (noted in memory).
2. **Create Palette Journal Entry**
   - Create `.jules/palette.md` with the critical learning about `focus-visible` styling and the `border-radius: inherit;` pitfall, following the required format.
3. **Verify frontend changes**
   - Use the `frontend_verification_instructions` tool to run the required Playwright script in `intelligence/company/www/`.
   - Take a screenshot of an interactive element in focus state.
   - Verify visually using `read_media_file`.
4. **Complete pre-commit steps**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.
5. **Submit the change**
   - Create a PR with the exact title prefix `🎨 Palette: [UX improvement]`.
   - Ensure the description includes What, Why, Before/After, and Accessibility sections.
