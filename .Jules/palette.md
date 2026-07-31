## 2026-04-21 - [Focus Indicators Missing]
**Learning:** This app's design system does not have default `:focus-visible` styles for accessible keyboard navigation or visual feedback for `:disabled` buttons, resulting in confusing interactions when keyboard-navigating or looking at inactive buttons in Trust Ops.
**Action:** Add universal `:focus-visible` and targeted `:disabled` styles to the core CSS file `meridian.css`.
