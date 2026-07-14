## 2026-07-14 - InnerHTML XSS Vulnerability in Frontend

**Vulnerability:** A Cross-Site Scripting (XSS) vulnerability was found in `meridian.js` where object properties were directly concatenated into HTML strings and rendered to the DOM using `.innerHTML` without escaping, specifically in the `renderInstitutionCard` function and the federation marketplace offerings catalog rendering.
**Learning:** This occurred because untrusted inputs (e.g. `inst.name`, `o.description`) were interpolated directly into the HTML markup string rather than being wrapped in the existing `escapeHtml()` utility function.
**Prevention:** Always sanitize/escape dynamic or untrusted data using `.textContent` where possible, or if `.innerHTML` string concatenation is necessary, wrap variables in an HTML escaping utility to prevent XSS.
