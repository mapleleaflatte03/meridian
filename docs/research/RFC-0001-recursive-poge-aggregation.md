# RFC-0001: Recursive PoGE Aggregation (Research Track)

## Status

- Type: research RFC
- Scope: `loom/` + `kernel/` proof interfaces
- Implementation state: **implemented** (P2 recursive chain + P3 hypercube aggregation)

## Objective

Current PoGE surfaces prove individual runtime slices. This RFC explores aggregating many governed actions into one verifiable receipt chain while preserving auditability.

## Hypothesis

If PoGE receipts can be recursively aggregated, Meridian can:

1. reduce proof-settlement overhead per action batch,
2. preserve sanction/warrant traceability,
3. keep replay/audit semantics deterministic.

## Design Sketch

1. Keep current per-action PoGE receipts unchanged.
2. Introduce aggregation envelope linking N receipts into one bundle receipt.
3. Emit bundle metadata in `kernel-proof-bundle` under a new optional section:
   - `aggregation.bundle_id`
   - `aggregation.member_receipts[]`
   - `aggregation.integrity_hash`
4. Preserve fallback:
   - if aggregation unavailable, single-receipt path remains source of truth.

## Trust Boundary Impact

- Must not weaken per-action audit trail.
- Court and treasury decisions must remain attributable to individual actions.
- Aggregation metadata cannot mask failed or sanctioned events.

## Acceptance Criteria

1. Deterministic replay for aggregated and non-aggregated paths.
2. Bundle verification includes all member receipt hashes.
3. Sanction path still references original action IDs.
4. Degraded mode cleanly falls back to non-aggregated proof path.

## Rollback

- Disable aggregation emitter.
- Continue publishing per-action PoGE receipts only.

## Implementation (P2 + P3)

### P2: Recursive Proof Chain

- `RecursiveProofNode`: per-action chain node with `chain_hash = H(tag || prev || receipt || warrant || action || depth)`
- `RecursiveProofBundle`: finalized bundle with `root_hash`, `max_depth`, `leaf_count`, `fallback_mode`
- Fallback mode preserves single-proof path when recursive mode is disabled
- 9 unit tests verify determinism, depth >= 2, parent linking, and fallback coexistence

### P3: Hypercube Proof Aggregation

- `HypercubeAggregate`: butterfly-pattern aggregation with XOR pairing across k dimensions
- `InclusionProof`: Merkle-tree-based inclusion proof for individual receipts within the aggregate
- `integrity_hash = H(tag || bundle_id || aggregate_root || member_receipts[])`
- 9 unit tests verify determinism, topology fields, inclusion verification, tamper detection

### API Surface

- `/api/status` exposes `proof.recursive` and `proof.aggregate` blocks
- `/api/runtime-proof` includes `recursive_proof` section
- `/api/kernel-proof-bundle` includes `aggregate` section with topology=hypercube

## Out of Scope

- No production settlement guarantee in this RFC.
- No claim of external chain settlement improvement yet.
