# Project Governance

This document defines how decisions and merges are handled in the Meridian monorepo.

## Decision Model

1. Runtime-critical and governance-critical changes must include acceptance evidence.
2. Research proposals begin as Discussion or `Research RFC` issue before implementation.
3. Public claims must stay inside verified runtime/API boundary.

## Merge Rules

- No direct feature development in archived mirrors.
- PRs should map to one primary module scope:
  - `loom/` runtime execution and adapters
  - `kernel/` governance primitives and economy surfaces
  - `intelligence/` public surfaces, gateway, workflows
- Changes touching multiple modules require explicit cross-module verification.

## Required Verification Before Merge

- Module tests for changed scope
- Acceptance lanes for changed operator/public surfaces
- Command evidence in PR description
- Rollback note for non-trivial behavior changes

## Ownership Guidance

- Maintainers retain final merge responsibility.
- Contributors can propose RFCs, docs, tests, and implementation PRs.
- Security-sensitive changes should prefer private review/disclosure flow first.

## Escalation

- Architecture disagreement -> GitHub Discussion
- Reproducible bug/regression -> GitHub Issue
- Security concern -> private security reporting
