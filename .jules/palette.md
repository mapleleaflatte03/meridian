## 2026-06-26 - Add global focus-visible states
**Learning:** Using a single global `:focus-visible` with `outline` is more robust and accessible than trying to style focus for individual components, provided we don't set a hardcoded `border-radius` which overrides browser native shapes.
**Action:** Implement global `:focus-visible` without `border-radius` to allow native curved boundaries based on the element's inherent radius.
