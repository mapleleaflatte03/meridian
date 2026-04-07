---
name: Bug report
about: Report a reproducible defect in Loom runtime, governance, or operator UX
title: "[bug] "
labels: bug
assignees: ""
---

## Summary

Describe the failure in one paragraph.

## Reproduction

1. Runtime root:
2. Command(s):
3. Expected result:
4. Actual result:

## Evidence

- `loom doctor --root ... --format json` output (redact sensitive values)
- `loom observe summary --root ... --format json --fix-hints`
- Relevant artifact paths (`parity`, `shadow`, `auth`, `observability`)

## Governance impact

- [ ] Court/sanction behavior affected
- [ ] Authority approval behavior affected
- [ ] Treasury/budget behavior affected
- [ ] Proof receipts/parity behavior affected

## Environment

- Loom version:
- Kernel path:
- OS/arch:
