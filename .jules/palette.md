## 2024-05-18 - Missing focus-visible outline
**Learning:** Found that there is no focus visible outline for a better keyboard navigation accessibility across all interactive components on the UI in `intelligence/company/www/assets/meridian.css`. Global `focus-visible` needs to avoid setting `border-radius` as modern browsers natively curve outlines.
**Action:** Always make sure `focus-visible` styles are globally set for all interactive components with high contrast outline.
