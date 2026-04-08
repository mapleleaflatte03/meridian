# Meridian Research Artifacts

This folder contains reproducible research artifacts for governed local AI agents.

## Contents

- `RFC-0001-recursive-poge-aggregation.md`
  - Proposal for recursive/aggregated PoGE proofs as an open research track.
- `BENCHMARK-0001-governance-runtime-baseline.md`
  - Reproducible benchmark protocol and baseline metrics contract.
- `CASE-STUDY-0001-sanction-remediation-loop.md`
  - End-to-end governance case study: detection -> sanction -> remediation.

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
