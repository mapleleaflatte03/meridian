## 2026-04-27 - Form Accessibility
**Learning:** The operator token input field in the trust-ops page form lacks a `required` attribute. This is an accessibility and UX issue as screen readers won't announce it as required and the browser won't enforce it before form submission, allowing incomplete submits.
**Action:** Add the `required` attribute to the `trust-ops-operator-token` input to enforce native client-side validation and improve accessibility.
