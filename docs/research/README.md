# Meridian Research Artifacts

This folder contains reproducible research artifacts for governed local AI agents.

## Contents

### RFC track

- `RFC-0001-recursive-poge-aggregation.md`
- `RFC-0002-hypercube-proof-aggregation.md`
- `RFC-0003-dynamic-constitutional-court.md`
- `RFC-0004-on-device-verifiable-agent-marketplace.md`

### Benchmarks

- `BENCHMARK-0001-governance-runtime-baseline.md`
- `BENCHMARK-0002-hypercube-aggregation-latency.md`
- `BENCHMARK-0003-dynamic-court-lifecycle.md`
- `BENCHMARK-0004-marketplace-settlement-dispute.md`
- `BENCHMARK-0005-memory-temporal-integrity.md`

### Case studies

- `CASE-STUDY-0001-sanction-remediation-loop.md`
- `CASE-STUDY-0002-hypercube-inclusion-verification.md`
- `CASE-STUDY-0003-dynamic-court-activation.md`
- `CASE-STUDY-0004-marketplace-dispute-resolution.md`
- `CASE-STUDY-0005-memory-integrity-mismatch.md`

## Contract Blocks (V4)

The `/api/status` endpoint exposes five contract blocks for verifiable governance:

| Block | Path | Fields |
|-------|------|--------|
| Recursive PoGE | `proof.recursive` | `enabled`, `depth`, `root` |
| Aggregate Proof | `proof.aggregate` | `topology`, `bundle_id`, `member_count`, `integrity_hash` |
| Dynamic Court | `court.dynamic` | `ruleset_version`, `proposal_count`, `active_rules` |
| Agent Marketplace | `marketplace` | `mode`, `open_bids`, `active_assignments`, `settled_count` |
| Memory Integrity | `memory.temporal_integrity` | `enabled`, `index_version` |

## Capture Scripts

- `scripts/research_capture_baseline.sh`
  - Captures stable baseline fields from `/api/status`, `/api/runtime-proof`, `/api/kernel-proof-bundle`, `/api/treasury`.
  - Includes all 5 V4 contract blocks in `contract_blocks` section.
- `scripts/research_capture_case_study.sh`
  - Captures before/after case snapshots and emits a normalized summary with invariants.

## Artifact Policy

1. Every artifact must include exact commands or payloads.
2. Every claim must define acceptance criteria and rollback caveats.
3. Artifacts are append-only history for research traceability.
4. Capture scripts should prefer boundary-stable fields over transient internals.

## Open vs Patent-Candidate Split

- Open research (default):
  - protocol specs
  - reference implementations
  - test harnesses
  - reproducible benchmarks and case studies
- Patent-candidate areas (documented, not restricted in this repo):
  - hypercube pairing optimization strategy
  - adaptive court sanction scoring policy
  - royalty-proof binding composition for settlement receipts
