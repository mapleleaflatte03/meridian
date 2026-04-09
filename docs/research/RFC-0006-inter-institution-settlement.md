# RFC-0006: Inter-Institution Treasury & Settlement Protocol

**Status:** Implemented  
**Authors:** Meridian Research Contributors  
**Created:** 2026-04-08  
**Layer:** L2 — Inter-Institution Treasury & Settlement  

## Abstract

This RFC defines the cross-institution settlement protocol that enables two or more
Meridian institutions to prepare, commit, and refund financial settlements for agent
work, with cryptographic proof receipts binding each state transition.

## Motivation

Single-institution marketplaces can settle agent work internally using the treasury
module. Cross-institution agent exchange requires a settlement protocol that:
1. Reserves funds before execution
2. Commits settlements with proof receipt verification
3. Supports court-ordered refunds with decision references
4. Computes royalty splits between worker and platform

## Protocol Design

### Settlement Lifecycle

```
prepare → committed → (settled | refunded)
```

### Prepare

`POST /api/commonwealth/settlement/prepare` creates a settlement reservation:

- `peer_org_id`: the counterparty institution
- `agent_id`: the agent being settled
- `amount_usd`: total settlement amount
- `royalty_rate`: fraction retained by platform (default 0.10)
- `action_ids`: optional list of action IDs for audit trail

Returns: `settlement_id`, `receipt_hash` (SHA-256 of settlement parameters),
`split` (worker_usd, royalty_usd breakdown).

### Commit

`POST /api/commonwealth/settlement/commit` transitions to `committed`:

- `proof_receipt`: the PoGE proof receipt hash from execution
- `warrant_ref`: optional KernelWarrant reference

The proof receipt is validated against the kernel proof chain. Settlement records
the proof validity status for audit.

### Refund

`POST /api/commonwealth/settlement/refund` transitions to `refunded`:

- `reason`: human-readable refund reason
- `court_decision_ref`: reference to court decision (from L3)

Refunds release the reserved treasury amount back to the originating institution.

### Receipt Hash

Each settlement generates a SHA-256 receipt hash binding:
`settlement_id || org_id || peer_org_id || agent_id || amount_usd`

This receipt is stored alongside the settlement and can be independently verified.

## Integration

- Treasury module (`kernel/kernel/treasury.py`) provides balance and reserve operations
- Marketplace module (`marketplace.py`) handles local bid/assign lifecycle
- Court module provides dispute resolution references

## Security Considerations

- Settlement amounts are validated positive with royalty rates in [0, 1)
- Proof receipt validation prevents settlement of unexecuted work
- Court decision references provide non-repudiable refund justification

## References

- RFC-0005: Commonwealth Federation
- Meridian Treasury: `kernel/kernel/treasury.py`
- Meridian Marketplace: `intelligence/company/meridian_platform/marketplace.py`
