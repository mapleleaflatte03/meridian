## 2026-04-14 - Added missing aria-label to trust-ops queue checkboxes
**Learning:** The Trust Ops operator queue renders dynamic checkboxes for bulk row selection. However, these inputs lack descriptive accessible names (ARIA labels) which is confusing for screen reader users navigating the table.
**Action:** Ensure dynamic JS table generations that include actionable form elements like checkboxes also generate appropriate aria-labels matching the row context (e.g., 'Select item [ID]').
