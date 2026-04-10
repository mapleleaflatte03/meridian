## 2024-04-10 - Screen Reader Context in Dynamic Tables
**Learning:** In dynamically generated tables with repeated actions per row (like 'Approve' / 'Revoke'), providing generic action labels creates ambiguity for screen reader users who navigate via elements list.
**Action:** When mapping array items to buttons, always concatenate the row's context (e.g., entity type or identifier) into the aria-label to uniquely distinguish the action.
