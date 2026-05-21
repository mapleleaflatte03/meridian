## 2024-05-24 - Missing visual feedback for disabled buttons
**Learning:** Disabled buttons (`<button disabled>`) lack visual cues to indicate their inactive state, leading to potential user confusion when bulk actions are unavailable.
**Action:** Always provide explicit opacity and `cursor: not-allowed;` for `:disabled` interactive elements in the base design system.
