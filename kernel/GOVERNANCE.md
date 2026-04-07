# Governance

## Current Model

Meridian Constitutional Kernel is maintained by its founding author
(Son Nguyen The) as benevolent dictator for life (BDFL) during the
early project phase.

This is practical, not ideological. A small project with one active
maintainer should not pretend to have a committee.

## Decision Making

### Small changes (bug fixes, docs, tests)
Lazy consensus. If a PR is clearly correct and passes CI, the maintainer
merges it.

### Medium changes (new features, API additions)
Maintainer review required. Discussion in the PR or a linked issue.

### Large changes (architecture, new primitives, breaking changes)
Requires an issue discussion before implementation. The maintainer
makes the final call but will explain reasoning publicly.

## Path to Broader Maintainership

As the project grows, the governance model will evolve:

1. **Current** — BDFL with community input via issues and PRs
2. **3+ regular contributors** — Add committer roles with write access
   to specific areas (e.g., economy layer, workspace UI, docs)
3. **Established community** — Move to a maintainer council model with
   documented decision process

Contributors who demonstrate consistent, high-quality contributions
will be invited to take on maintainer responsibilities.

## Dogfooding

This project is governed by its own primitives. The kernel's concepts
of authority, accountability, and transparency apply to the project
itself:

- All significant decisions leave an artifact (issue, PR, or commit)
- Authority to merge is earned through contribution, not title
- The audit trail (git history) is the project's court record

## Code of Conduct

All participants are expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Contact

Project maintainer: nguyensimon186@gmail.com
