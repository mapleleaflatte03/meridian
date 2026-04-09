# RFC-0007: Dynamic Constitutional Federation

**Status:** Implemented  
**Authors:** Meridian Research Contributors  
**Created:** 2026-04-08  
**Layer:** L3 — Dynamic Constitutional Federation  

## Abstract

This RFC specifies the cross-institution court rule propagation protocol that enables
a Meridian institution to propagate governance rules (court rules, constitutional
amendments) to federation peers via signed envelopes.

## Motivation

Each Meridian institution has its own court system with rules, proposals, and
violation resolution. When institutions federate, governance alignment requires
a mechanism to propagate rule changes across the federation without imposing a
single authority. This protocol enables cooperative governance while preserving
institutional sovereignty.

## Protocol Design

### Rule Propagation

`POST /api/commonwealth/court/propagate` sends a court rule to a federation peer:

- `peer_host_id`: target peer in the federation
- `rule_id`: unique identifier for the rule
- `rule_text`: full text of the rule
- `ruleset_version`: version of the ruleset this rule belongs to

### Propagation Envelope

When the full federation module is available, the rule is wrapped in an HMAC-SHA256
signed envelope via `FederationAuthority.issue()`:

```json
{
  "type": "court_rule_propagation",
  "rule_id": "rule_001",
  "rule_text": "No unauthorized agent execution across federation boundaries",
  "ruleset_version": "2.0.0",
  "source_org_id": "org_a",
  "propagation_id": "prop_abc123"
}
```

### Delivery States

| State | Meaning |
|-------|---------|
| `envelope_issued` | Signed envelope created, ready for delivery |
| `queued_local` | Federation module unavailable; stored locally for later delivery |
| `delivered` | Envelope successfully received by peer |
| `rejected` | Peer rejected the rule (signature invalid, policy conflict) |

### Propagation Record

All propagations are recorded in `commonwealth_propagations.json` for audit:

```json
{
  "propagation_id": "prop_abc123",
  "peer_host_id": "host_org_b",
  "rule_id": "rule_001",
  "ruleset_version": "2.0.0",
  "delivery_status": "envelope_issued",
  "created_at": "2026-04-08T20:00:00Z"
}
```

### Receiving Side

The receiving institution processes propagated rules through:
1. Envelope signature validation (HMAC-SHA256)
2. Replay protection (envelope-id deduplication)
3. Local court system integration (rule proposal or auto-adopt based on policy)

## Governance Semantics

- Propagated rules are **advisory** by default — the receiving institution's court
  decides whether to adopt, modify, or reject.
- **Mandatory** propagation can be enabled via constitutional agreements between
  specific peers (bilateral or multilateral).
- Rule conflicts are resolved by the receiving institution's court, not the sender.

## Security Considerations

- Envelope signing prevents rule tampering in transit
- Replay store prevents duplicate rule application
- Receiving institutions maintain sovereignty over rule adoption

## References

- RFC-0003: Dynamic Constitutional Court
- RFC-0005: Commonwealth Federation
- Meridian Court: `kernel/kernel/court.py`
- Meridian Federation: `intelligence/company/meridian_platform/federation.py`
