# RFC-0002: Hypercube Proof Aggregation

Status: Draft (implementable)  
Owners: Loom + Kernel maintainers  
Scope: `proof.aggregate` contract block and `/api/kernel-proof-bundle`

## Problem

Single-action proof receipts are expensive to inspect at scale. Operators need one aggregate bundle plus inclusion proofs to verify member receipts without replaying every action.

## Proposal

Introduce a hypercube aggregation layer over recursive PoGE leaves.

Data structure:

- `HypercubeAggregate { bundle_id, dimension, member_receipts[], level_hashes[], aggregate_root, integrity_hash }`
- `InclusionProof { receipt_hash, index, sibling_path[] }`

Pseudocode:

```text
for d in 0..k-1:
  pair(i) = i xor (1<<d)
  level[d+1][i] = H(level[d][i] || level[d][pair(i)])
aggregate_root = level[k][0]
integrity_hash = H(bundle_id || aggregate_root || member_receipts[])
```

## API/Contract Impact

- `/api/status` -> `proof.aggregate.{topology,bundle_id,member_count,integrity_hash}`
- `/api/kernel-proof-bundle` aggregate payload MUST include:
  - `topology=hypercube`
  - `dimension`
  - `bundle_id`
  - `member_receipts[]`
  - `inclusion_proofs[]`
  - `inclusion_verified`
  - `aggregate_root`
  - `integrity_hash`

## Acceptance Criteria

1. Inclusion proof verifies for sampled members.
2. Aggregate payload maps to real receipt hashes (no synthetic-only metadata).
3. Backward-compatible fields remain present for existing consumers.

## Rollback

Set aggregate generation back to legacy Merkle metadata-only path while keeping schema keys stable.

## References

- `kernel/examples/generate_public_proof_bundle.py`
- `intelligence/company/meridian_platform/workspace.py`
