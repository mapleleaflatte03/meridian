# Intellectual Property Split

This document clarifies the boundary between open-source components and
patent-candidate innovations in the Meridian Commonwealth platform.

## Open (Apache-2.0 / MIT)

All of the following are fully open-source, reproducible, and available for
research, commercial, and educational use:

| Component | Scope |
|-----------|-------|
| **Protocol specifications** | RFCs 0001-0009 (PoGE, aggregation, court, marketplace, federation, settlement, constitutional federation, agent exchange, temporal memory) |
| **Reference implementations** | `loom/` (Rust runtime), `kernel/` (Python governance), `intelligence/` (Python platform) |
| **Test suites** | All acceptance lanes, E2E scripts, unit tests, integration tests |
| **Reproducible benchmarks** | BENCHMARK-0001 through BENCHMARK-0010 |
| **Case studies** | CASE-STUDY-0001 through CASE-STUDY-0010 |
| **Documentation** | All docs under `docs/`, `docs/research/`, README, CONTRIBUTING, etc. |
| **CI/CD workflows** | All GitHub Actions workflows |
| **Commonwealth module** | `commonwealth.py` — all 5 layers (L1-L5) |
| **Federation module** | `federation.py` — HMAC-SHA256 envelope signing, peer registry |
| **Marketplace module** | `marketplace.py` — bid/assign/settle/dispute lifecycle |
| **Memory graph module** | `memory_graph.py` — hash-chained temporal memory |

## Patent-Candidate Innovations

The following novel algorithmic contributions may be subject to patent filings.
They remain published and documented for research reproducibility, but commercial
use of the specific algorithmic innovations (not the open-source implementations)
may require licensing:

### 1. Hypercube Pairing Strategy

**RFC:** RFC-0002  
**Innovation:** The specific topology for aggregating recursive PoGE proofs into a
hypercube structure where each node represents an (agent, action) pair and edges
represent governance dependencies. The pairing strategy achieves O(log n) verification
depth while maintaining full audit trail.

**Open:** The hypercube data structure, serialization format, and verification algorithm.  
**Patent-candidate:** The specific adaptive pairing heuristic that minimizes
cross-institution verification overhead while preserving proof density.

### 2. Adaptive Court Sanction Scoring

**RFC:** RFC-0003  
**Innovation:** The scoring algorithm that dynamically adjusts sanction severity
based on violation history, institutional trust score, and federation context.
The algorithm uses a decay function with configurable half-life and escalation
thresholds.

**Open:** The court rule lifecycle, proposal/vote/activate protocol, and violation resolution flow.  
**Patent-candidate:** The specific adaptive scoring function with federation-aware
escalation and cross-institution sanction propagation weighting.

### 3. Royalty-Proof Binding

**RFC:** RFC-0006, RFC-0008  
**Innovation:** The cryptographic binding between royalty split computations and
PoGE proof receipts, ensuring that royalty percentages cannot be altered after
settlement without invalidating the proof chain. The binding uses a commit-reveal
scheme where the royalty rate is committed before execution and revealed during
settlement.

**Open:** The settlement lifecycle, royalty split computation, and proof receipt validation.  
**Patent-candidate:** The specific commit-reveal binding protocol that prevents
post-hoc royalty manipulation in cross-institution settlements.

## Boundary Principle

When in doubt, the component is open-source. Patent candidates are narrowly scoped
to specific algorithmic innovations, not broad protocol categories. The reference
implementations of all patent-candidate algorithms are open-source and reproducible.

## Contact

For licensing inquiries about patent-candidate innovations:
- Open an issue at [github.com/mapleleaflatte03/meridian](https://github.com/mapleleaflatte03/meridian/issues)
- Reference this document and the specific innovation
