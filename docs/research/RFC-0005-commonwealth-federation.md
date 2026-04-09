# RFC-0005: Commonwealth Federation Layer on PoGE

**Status:** Implemented  
**Authors:** Meridian Research Contributors  
**Created:** 2026-04-08  
**Layer:** L1 — Federation Layer on PoGE  

## Abstract

This RFC specifies the Commonwealth Federation protocol that enables multiple Meridian
institutions to form a verifiable federation using Proof of Governed Execution (PoGE)
as the trust primitive. Each institution maintains its own governance context while
participating in cross-institution proof bundles.

## Motivation

Single-institution deployments of Meridian can verify their own agent executions, but
cross-institution workflows (agent exchange, settlement, court propagation) require a
shared trust layer. Federation on PoGE extends the existing per-institution proof
chain to cover inter-institution interactions without requiring a central authority.

## Protocol Design

### Peer Registry

Each institution maintains a `federation_peers.json` file containing admitted peers:

```json
{
  "peers": {
    "host_org_b": {
      "trust_state": "admitted",
      "transport": "http",
      "endpoint_url": "https://org-b.example.com/api/federation/receive",
      "admitted_org_ids": ["org_b"]
    }
  }
}
```

### Federation Linking

`POST /api/commonwealth/federation/link` upserts a peer entry. The link operation
writes to the peer registry and returns a `link_id` for audit traceability.

When the full federation module is available (FederationAuthority with HMAC-SHA256
envelope signing), links are written to the cryptographic peer registry. When
unavailable, a fallback local store is used, preserving the same API surface.

### Federated Proof Bundle

`GET /api/commonwealth/proof-bundle` returns:

1. The kernel proof bundle (recursive PoGE aggregate from loom-poge)
2. Federation context (peer count, enabled status, protocol version)
3. Memory anchor (temporal integrity head hash and chain validity)

This bundle is the trust primitive for cross-institution verification: any peer
can independently verify the proof chain and federation state.

### Envelope Protocol

Cross-institution messages use HMAC-SHA256 signed envelopes via `FederationAuthority.issue()`.
Each envelope includes:
- `source_institution_id`
- `target_host_id`
- `target_institution_id`
- `payload` (the message body)
- `action_kind` (e.g., `court_rule_propagation`, `settlement_commit`)

Recipients validate the envelope signature against their peer registry before processing.

## Security Considerations

- Peer registry is file-based with atomic writes; production deployments should use
  a distributed store with consensus.
- HMAC-SHA256 provides integrity but not non-repudiation; Ed25519 (via KernelWarrant)
  is used for warrant-level signing.
- Replay protection is handled by `ReplayStore` with envelope-id deduplication.

## Extension Points

- **Multi-hop federation:** Current design is direct peer-to-peer; future work could
  add transitive trust chains.
- **Zero-knowledge federation proofs:** Replace HMAC with ZK proofs for privacy-preserving
  cross-institution verification.

## References

- RFC-0001: Recursive PoGE Aggregation
- RFC-0002: Hypercube Proof Aggregation
- Meridian Federation Module: `intelligence/company/meridian_platform/federation.py`
- Commonwealth Module: `intelligence/company/meridian_platform/commonwealth.py`
