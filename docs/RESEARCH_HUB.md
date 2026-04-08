# Meridian Research Hub

**Meridian — Open Research Platform for Verifiable AI Commonwealth**

This page collects canonical research artifacts for governance and verifiable local agent execution across institutions.

## Core Artifacts (Canonical)

- PoGE protocol: `loom/docs/MERIDIAN_PoGE_PROTOCOL.md`
- Runtime benchmarks: `loom/docs/BENCHMARKS.md`
- Cross-stack architecture: `intelligence/ARCHITECTURE.md`
- Kernel + Loom boundary notes: `kernel/docs/LOOM_SPEC.md`
- Public roadmap: `ROADMAP.md`
- Community routing for RFCs: `docs/COMMUNITY_MAP.md`
- Research artifacts index: `docs/research/README.md`
- Recursive PoGE RFC draft: `docs/research/RFC-0001-recursive-poge-aggregation.md`
- Hypercube RFC draft: `docs/research/RFC-0002-hypercube-proof-aggregation.md`
- Dynamic Court RFC draft: `docs/research/RFC-0003-dynamic-constitutional-court.md`
- Marketplace RFC draft: `docs/research/RFC-0004-on-device-verifiable-agent-marketplace.md`
- Governance runtime baseline benchmark: `docs/research/BENCHMARK-0001-governance-runtime-baseline.md`
- Hypercube benchmark: `docs/research/BENCHMARK-0002-hypercube-aggregation-latency.md`
- Dynamic court benchmark: `docs/research/BENCHMARK-0003-dynamic-court-lifecycle.md`
- Marketplace benchmark: `docs/research/BENCHMARK-0004-marketplace-settlement-dispute.md`
- Memory integrity benchmark: `docs/research/BENCHMARK-0005-memory-temporal-integrity.md`
- Sanction/remediation case study: `docs/research/CASE-STUDY-0001-sanction-remediation-loop.md`
- Hypercube inclusion case study: `docs/research/CASE-STUDY-0002-hypercube-inclusion-verification.md`
- Dynamic court activation case study: `docs/research/CASE-STUDY-0003-dynamic-court-activation.md`
- Marketplace dispute case study: `docs/research/CASE-STUDY-0004-marketplace-dispute-resolution.md`
- Memory mismatch case study: `docs/research/CASE-STUDY-0005-memory-integrity-mismatch.md`
- Baseline capture script: `scripts/research_capture_baseline.sh`
- Case-study capture script: `scripts/research_capture_case_study.sh`

## Commonwealth RFC Track (V5)

- Commonwealth federation RFC: `docs/research/RFC-0005-commonwealth-federation.md`
- Inter-institution settlement RFC: `docs/research/RFC-0006-inter-institution-settlement.md`
- Dynamic constitutional federation RFC: `docs/research/RFC-0007-dynamic-constitutional-federation.md`
- Verifiable agent exchange RFC: `docs/research/RFC-0008-verifiable-agent-exchange.md`
- Temporal memory commonwealth chain RFC: `docs/research/RFC-0009-temporal-memory-commonwealth-chain.md`
- IP split document: `docs/IP_SPLIT.md`

## PoGE + Governance RFC Track

Use the `Research RFC` issue template to propose protocol/runtime changes:

- Template: `.github/ISSUE_TEMPLATE/research_rfc.yml`
- Open RFC issue: `https://github.com/mapleleaflatte03/meridian/issues/new/choose`

Every RFC must include:

1. trust-boundary impact,
2. measurable acceptance criteria,
3. rollback strategy.

## V5 Contract Blocks

The `/api/status` endpoint includes seven contract blocks:

- `proof.recursive.{enabled,depth,root}` — single-session recursive PoGE
- `proof.aggregate.{topology,bundle_id,member_count,integrity_hash}` — hypercube aggregate bundle
- `court.dynamic.{ruleset_version,proposal_count,active_rules}` — dynamic constitutional court
- `marketplace.{mode,open_bids,active_assignments,settled_count}` — verifiable agent marketplace
- `memory.temporal_integrity.{enabled,index_version}` — temporal memory chain
- `commonwealth.federation.{enabled,peer_count,last_sync_ms}` — inter-institution federation
- `commonwealth.settlement.{inter_institution_enabled,pending_count,settled_count}` — cross-institution settlement

These blocks are captured by the baseline script under the `contract_blocks` key. See `docs/research/README.md` for the full field reference.

## V4 Contract Blocks (Superseded by V5)

V4 defined the first five blocks above. V5 adds the `commonwealth` block. All V4 fields are preserved.

## Baseline Reproduction Commands

```bash
# Loom benchmark harness
cd loom
python3 scripts/bench_runtime.py --help

# Runtime proof surface checks
curl -fsS http://127.0.0.1:8266/api/runtime-proof
curl -fsS http://127.0.0.1:8266/api/kernel-proof-bundle

# Governance state checks
curl -fsS http://127.0.0.1:8266/api/institution/template
curl -fsS http://127.0.0.1:8266/api/treasury
curl -fsS http://127.0.0.1:8266/api/status

# Canonical capture scripts (runtime/research/*.json)
./scripts/research_capture_baseline.sh
./scripts/research_capture_case_study.sh sanction_remediation_loop
```

## V4 Implementation Summary

The V4 contract is validated by gate scripts and route probes, not by static claims.
Use the commands in this document to verify the current runtime state directly.

### API Endpoints Added

**Court (P4):** `/api/court/propose`, `/api/court/vote`, `/api/court/tally`, `/api/court/activate`, `/api/court/proposals`, `/api/court/proposals/activate`, `/api/court/rules`

**Marketplace (P5):** `/api/marketplace`, `/api/marketplace/bid`, `/api/marketplace/bids`, `/api/marketplace/assign`, `/api/marketplace/settle`, `/api/marketplace/dispute`, `/api/marketplace/cancel`, `/api/marketplace/settlements`, `/api/marketplace/disputes`

**Memory (Track M):** `/api/memory/append`, `/api/memory/verify`, `/api/memory/query`, `/api/memory/head`

## Moat/IP Split

- Open:
  - protocol specs and RFCs
  - reference implementations and tests
  - reproducible benchmarks and case studies
- Patent-candidate (documented candidate areas):
  - hypercube pairing optimization strategy
  - adaptive court sanction scoring design
  - royalty-proof binding design for settlement receipts

### Rust Crate: loom-poge

58 tests total — 40 original + 9 recursive chain + 9 hypercube aggregation.

## Killer Example (Governed Runtime Loop)

Minimal example to show why Meridian is different from generic local-agent runtimes:

1. bootstrap stack (`./scripts/bootstrap_full.sh`)
2. start services (`./scripts/dev-up.sh`)
3. inspect institution template and court rules
4. inspect treasury reserve discipline
5. inspect runtime proof + kernel proof bundle

Expected evidence:

- institution template schema present (`meridian.institution_template.v1`)
- court rules initialized (>=3)
- treasury snapshot carries balance + reserve floor
- runtime proof route and kernel proof bundle are reachable and coherent

## Suggested Research Outputs

- benchmark notes (`loom/docs/BENCHMARKS.md`)
- proof-route audits (`/api/runtime-proof`, `/api/kernel-proof-bundle`)
- governance case studies (incident -> sanction -> remediation traces)
- RFC history under `docs/research/`

Keep outputs reproducible: include exact commands, payload snippets, and module/commit context.
