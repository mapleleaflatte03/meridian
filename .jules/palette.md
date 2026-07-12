## 2026-07-12 - Missing global focus-visible styles
**Learning:** Found that global interactive elements (links, buttons, form controls not under .intake-field) in meridian.css lack explicit focus styles (:focus-visible), making keyboard navigation inaccessible. Only .intake-field inputs had custom focus.
**Action:** Add explicit global :focus-visible styles to a, button, input, textarea, select in meridian.css using the existing --accent token and an outline offset, ensuring keyboard navigation is obvious across the whole site.
