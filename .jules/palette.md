## 2024-10-15 - Dynamic title updates for disabled states
**Learning:** When adding static accessibility attributes like `title` to explain disabled states, if those states are dynamically toggled via JavaScript, the attributes must also be dynamically toggled. Otherwise, the disabled explanation persists after the element becomes active, misleading users.
**Action:** Always check if a disabled element is dynamically re-enabled, and if so, write JavaScript logic to remove the static explanation attribute (e.g. `removeAttribute('title')`) simultaneously.
