# Meridian Community

**Meridian — Open Research Platform for Verifiable AI Commonwealth**

This document covers how to participate in the Meridian project community.

## Community Hub

- **Monorepo:** https://github.com/mapleleaflatte03/meridian
- **Issues:** https://github.com/mapleleaflatte03/meridian/issues/new/choose
- **Pull Requests:** https://github.com/mapleleaflatte03/meridian/pulls
- **Discussions:** https://github.com/mapleleaflatte03/meridian/discussions
- **Contribution Guide:** [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- **Roadmap:** [`ROADMAP.md`](../ROADMAP.md)

## How to Participate

### Code Contributions

- Pick an issue labeled `good first issue`, `research`, or `governance`.
- Bootstrap the full stack: `./scripts/bootstrap_full.sh`
- Run the relevant module tests before submitting a PR.
- Submit against the monorepo main branch.

### Documentation

- Improve module docs, README sections, or research artifact descriptions.
- All docs live in the monorepo under `docs/`, `loom/docs/`, `kernel/docs/`, `intelligence/`.

### Research and RFCs

- Propose protocol changes via the `Research RFC` issue template.
- RFCs must include: trust-boundary impact, measurable acceptance criteria, rollback strategy.
- RFC artifacts live under `docs/research/`.

### Benchmarks and Case Studies

- Reproducible benchmarks and governance case studies go under `docs/research/`.
- Capture scripts: `scripts/research_capture_baseline.sh`, `scripts/research_capture_case_study.sh`.

### Governance Modules

- Institution templates, court rule sets, and treasury baselines welcome as contributions.
- Test coverage required (see `CONTRIBUTING.md`).

## Contribution Principles

1. All contributions happen in the monorepo — archived mirrors are read-only.
2. PRs require passing CI and tests for affected modules.
3. Governance-affecting changes require an RFC or issue discussion first.
4. Code of conduct applies to all community spaces: [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md)

## Review and Merge Governance

- Core maintainers review PRs within the issue milestone cycle.
- Research PRs (RFCs, benchmarks) reviewed by maintainers and community members.
- Merge requires: CI green, at least 1 approval, no blocking objections.

## RFC Process

1. Open a `Research RFC` issue with the required fields.
2. Discussion period (7+ days for governance-scope changes).
3. Implement with acceptance criteria and rollback notes.
4. Submit PR with artifact files under `docs/research/`.

## Support

Optional support for the project:

- GitHub Sponsors: https://github.com/sponsors/mapleleaflatte03
- Consulting/research grants: contact via GitHub issues
- Sustainability policy: [`docs/SUSTAINABILITY.md`](SUSTAINABILITY.md)
