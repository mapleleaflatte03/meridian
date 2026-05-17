## 2024-05-17 - Button disabled states missing cursor and opacity
**Learning:** Found that operator action buttons (and other buttons) in the app do not have visual feedback when disabled. `button:disabled` pseudo-class is missing from `meridian.css`, leading to poor UX where disabled buttons look identical to active ones and still show a pointer cursor.
**Action:** Always add explicit styling for `:disabled` states on buttons, typically reducing opacity and changing the cursor to `not-allowed`.
