# Commonwealth Readiness Report
**Version:** V5  
**Date:** 2026-04-08  
**Gate:** P-0 — Deep Scan Readiness  
**Verdict:** GO

---

## 1. Scan Manifest

Files scanned:

| File | Lines |
|------|-------|
| `loom/crates/loom-poge/src/lib.rs` | 1997 |
| `loom/crates/loom-poge/src/sp1.rs` | 147 |
| `kernel/kernel/court.py` | 788 |
| `kernel/kernel/treasury.py` | 4044 |
| `intelligence/company/meridian_platform/workspace.py` | 8432 |
| `intelligence/company/meridian_platform/federation.py` | 1005 |
| `intelligence/company/meridian_platform/marketplace.py` | 361 |
| `intelligence/company/meridian_platform/memory_graph.py` | 385 |

Supporting crates (loom-core) also scanned:

| File | Status |
|------|--------|
| `loom/crates/loom-core/src/agent_marketplace.rs` | PRESENT |
| `loom/crates/loom-core/src/memory_hybrid.rs` | PRESENT |
| `loom/crates/loom-core/src/event_sourcing.rs` | PRESENT |

---

## 2. Capability Matrix

| Layer | Component | Status | Notes |
|-------|-----------|--------|-------|
| **L1 Federation on PoGE** | `FederationAuthority` (federation.py) | PRESENT | HMAC-SHA256 envelope signing, peer registry, replay store |
| **L1 Federation on PoGE** | `KernelWarrant` Ed25519 (loom-poge/lib.rs) | PRESENT | warrant_id + sig flows into every HostCallReceipt |
| **L1 Federation on PoGE** | `/api/status commonwealth.federation` block | MISSING | federation state lives under `runtime_core.federation` — needs top-level `commonwealth` key |
| **L2 Inter-Institution Treasury** | `settle_bid()` + royalty split (marketplace.py) | PRESENT | domain-separated receipt hash, royalty_share, settlement ledger |
| **L2 Inter-Institution Treasury** | `treasury.py` capsule ledger + payout plan | PRESENT | multi-contributor ledger, x402 transfer, accounting hooks |
| **L2 Inter-Institution Treasury** | `/api/status commonwealth.settlement` block | MISSING | needs `inter_institution_enabled`, `pending_count`, `settled_count` |
| **L3 Dynamic Constitutional Federation** | `court.py` dynamic rules + proposals | PRESENT | ruleset_version=9, 9 active rules, proposal/vote/auto-review |
| **L3 Dynamic Constitutional Federation** | `/api/court/rules` endpoint | PRESENT | live, returns 9 rules |
| **L3 Dynamic Constitutional Federation** | Cross-institution rule propagation | MISSING | no `propagate()` in court_service.py or federation delivery path yet |
| **L4 Verifiable Agent Exchange** | `post_bid / assign_bid / settle_bid / open_dispute / resolve_dispute` (marketplace.py) | PRESENT | full lifecycle, dispute decisions: stay/refund/release |
| **L4 Verifiable Agent Exchange** | `Marketplace` Rust struct + receipt binding (agent_marketplace.rs) | PRESENT | Bid/Assignment/Settlement with PoGE proof_hash |
| **L4 Verifiable Agent Exchange** | `/api/commonwealth/marketplace/*` routes | MISSING | P-7 target |
| **L5 Temporal Memory Chain** | `append_node / verify_chain / temporal_query_with_proof` (memory_graph.py) | PRESENT | hash-chained nodes, `who knew what when` query, integrity proof |
| **L5 Temporal Memory Chain** | `TemporalEntry` + Merkle provenance (memory_hybrid.rs) | PRESENT | valid_from/valid_until, cosine similarity, Merkle root |
| **L5 Temporal Memory Chain** | `/api/commonwealth/memory/anchor` | MISSING | P-7 target |

---

## 3. Blockers

### Structural Blockers (NONE — all extension points confirmed)
No rewrites are required. All 5 layers have solid primitives.

### API Contract Gaps (P-1 targets)
1. `/api/status` is missing `commonwealth.federation.{enabled,peer_count,last_sync_ms}` — add stub block in `api_status()` pulling from `_federation_snapshot()`.
2. `/api/status` is missing `commonwealth.settlement.{inter_institution_enabled,pending_count,settled_count}` — add stub block.

### Protocol Gaps (P-7 targets)
3. `/api/commonwealth/federation`, `/api/commonwealth/federation/link` — not yet registered in workspace.py router.
4. `/api/commonwealth/settlement/{prepare,commit,refund}` — not yet registered.
5. `/api/commonwealth/court/propagate` — no cross-institution court propagation path.
6. `/api/commonwealth/marketplace/{publish,acquire}` — not yet registered.
7. `/api/commonwealth/memory/anchor`, `/api/commonwealth/proof-bundle` — not yet registered.
8. No persistent cross-institution peer linkage (currently single-host founding deployment).

---

## 4. Exact Extension Points Per Module

### 4.1 Federation Layer on PoGE (L1)

**Module:** `intelligence/company/meridian_platform/federation.py`

- `FederationAuthority.issue()` — attach `warrant_id` + `commitment_id` fields (already in FederationEnvelopeClaims slots) to federated PoGE proofs.
- `FederationAuthority.deliver()` — wire to `/api/commonwealth/federation/link` POST handler for live cross-institution federation.
- `_federation_snapshot()` in workspace.py — already returns `peer_count`, `last_sync_ms`, `enabled`. Needs to be re-surfaced under top-level `commonwealth.federation` key in `api_status()`.
- `load_peer_registry()` / `save_peer_registry()` — basis for persisting commonwealth peer state; extend with `commonwealth_peers` field.

**Module:** `loom/crates/loom-poge/src/lib.rs`

- `PoGEAuditRoot` + `ZkPoGEProof` — extend with optional `peer_host_id` field for federated proof bundle inclusion.
- New fn: `federated_proof_bundle(roots: &[PoGEAuditRoot]) -> FederatedProofBundle` — aggregate Merkle root over multi-institution sessions; add to loom-poge as `federation` submodule.

### 4.2 Inter-Institution Treasury & Settlement (L2)

**Module:** `intelligence/company/meridian_platform/marketplace.py`

- `settle_bid(bid_id, proof_receipt, settled_by, org_id=...)` — already accepts `org_id`; add `peer_org_id` param for cross-institution settlement routing.
- `_deterministic_split()` — already implements royalty split; extend with `inter_institution_fee` param.
- New fn: `prepare_inter_institution_settlement(org_id_a, org_id_b, bid_id, ...)` — creates escrow record spanning two institutions.
- New fn: `commit_inter_institution_settlement(...)` / `refund_inter_institution_settlement(...)` — complete or refund cross-institution escrow.

**Module:** `kernel/kernel/treasury.py`

- `treasury_snapshot(org_id)` — add `inter_institution_pending_count` + `inter_institution_settled_count` to the snapshot output for `/api/status`.
- `sign-x402-transfer` path — reusable for cross-institution on-chain settlement finalization.

### 4.3 Dynamic Constitutional Federation (L3)

**Module:** `kernel/kernel/court.py`

- `auto-review` subcommand — basis for scheduled rule propagation trigger.
- `_load_records()` / `_dynamic_projection_paths()` — extend to accept `peer_org_ids` list for federated rule sync.
- New fn: `propagate_ruleset(from_org_id, to_peer_host_ids, via_federation_authority)` — issues federation envelope with message_type `court_ruleset_update`.

**Module:** `intelligence/company/meridian_platform/workspace.py`

- `_process_received_federation_message()` at line 2886 — add handler branch for `message_type == 'court_ruleset_update'` to apply received rules.
- Register POST `/api/commonwealth/court/propagate`.

### 4.4 Verifiable Agent Exchange Protocol (L4)

**Module:** `intelligence/company/meridian_platform/marketplace.py`

- All core functions (`post_bid`, `assign_bid`, `settle_bid`, `open_dispute`, `resolve_dispute`) accept `org_id` — add optional `source_org_id` / `target_org_id` params for cross-institution routing.
- New fn: `publish_agent_cross_institution(agent_id, from_org_id, to_peer_host_id, ...)` — wraps `post_bid` in a federation envelope.
- New fn: `acquire_agent_cross_institution(bid_id, acquiring_org_id, ...)` — wraps `assign_bid`.

**Module:** `loom/crates/loom-core/src/agent_marketplace.rs`

- `Marketplace.submit_bid()` / `Marketplace.assign()` / `Marketplace.settle()` — add optional `peer_institution_id: Option<String>` field to `Bid` for cross-institution attribution.
- Extend `SettlementStatus` with `CrossInstitutionPending` variant.

### 4.5 Temporal Memory Commonwealth Chain (L5)

**Module:** `intelligence/company/meridian_platform/memory_graph.py`

- `append_node(key, value, org_id=...)` — already accepts `org_id`; add `peer_org_id` + `anchor_hash` params for cross-institution anchoring.
- `temporal_query_with_proof()` — returns chain_valid + head_hash + proof_nodes; expose via `/api/commonwealth/memory/anchor`.
- `verify_temporal_proof()` — use for cross-institution "who knew what when" verification.
- New fn: `anchor_cross_institution(org_id_a, org_id_b, federation_authority)` — appends anchor node with `peer_head_hash` from org_b into org_a's chain via federation envelope.

**Module:** `loom/crates/loom-core/src/memory_hybrid.rs`

- `TemporalEntry` struct — add optional `peer_institution_id: Option<String>` and `anchor_proof: Option<String>` fields.
- New fn: `federated_merkle_root(entries: &[TemporalEntry]) -> [u8; 32]` — aggregate cross-institution Merkle root.

---

## 5. GO/NO-GO Verdict

### Assessment

| Layer | Extension Points Confirmed | GO? |
|-------|---------------------------|-----|
| L1 Federation Layer on PoGE | FederationAuthority.issue/deliver, KernelWarrant.id binding, _federation_snapshot | **GO** |
| L2 Inter-Institution Treasury & Settlement | settle_bid + org_id routing, treasury_snapshot extension, x402 path | **GO** |
| L3 Dynamic Constitutional Federation | court.py auto-review + dynamic rules, _process_received_federation_message hook | **GO** |
| L4 Verifiable Agent Exchange Protocol | marketplace.py full lifecycle with org_id, agent_marketplace.rs Bid/Settlement structs | **GO** |
| L5 Temporal Memory Commonwealth Chain | memory_graph.py temporal_query_with_proof, append_node + org_id, memory_hybrid.rs TemporalEntry | **GO** |

### Verdict: **GO**

The system is ready for commonwealth-level expansion without rewrite. All 5 required layers have confirmed extension points in production code. The gap set is additive-only: new API routes, new top-level status blocks, and cross-institution parameter threading in existing functions. No existing governance semantics (PoGE + warrant + court + authority + treasury + 3-ledger) need modification.

Proceed to P-1: Vision Lock + Contract Lock.

---

*Generated by Meridian Commonwealth Execution Contract V5 — Gate P-0*
