# RFC-0008: Verifiable Agent Exchange Protocol

**Status:** Implemented  
**Authors:** Meridian Research Contributors  
**Created:** 2026-04-08  
**Layer:** L4 — Verifiable Agent Exchange Protocol  

## Abstract

This RFC specifies the cross-institution agent exchange protocol that enables
institutions to publish agents to a commonwealth marketplace, acquire them across
federation boundaries, and settle with cryptographic proof verification.

## Motivation

The single-institution marketplace (RFC-0004) enables bid/assign/settle/dispute
within one institution. Cross-institution agent exchange requires:
1. A shared listing surface visible to federation peers
2. Acquisition with reservation tracking
3. Settlement that bridges two treasury systems
4. Proof receipts that span institution boundaries

## Protocol Design

### Publish

`POST /api/commonwealth/marketplace/publish` creates a commonwealth listing:

- `agent_id`: the agent being published
- `task_description`: what the agent does
- `amount_usd`: listing price
- `royalty_rate`: platform royalty fraction
- `federation_scope`: list of peer org_ids (or `"open"` for all)
- `action_ids`: execution action references

Returns: `listing_id`, `receipt_hash`, `status: "open"`.

The listing is also mirrored to the local marketplace via `post_bid()` to maintain
the local proof receipt chain.

### Acquire

`POST /api/commonwealth/marketplace/acquire` assigns a listing to an acquirer:

- `listing_id`: the commonwealth listing
- `acquirer_org_id`: the acquiring institution
- `reservation_note`: optional note

The acquisition:
1. Validates the listing is `open`
2. Creates an acquisition record with a `reservation_id`
3. Assigns the local marketplace bid if present
4. Transitions the listing to `acquired` status

Returns: `acquisition_id`, `reservation_id`, `agent_id`, `amount_usd`.

### Settlement Bridge

After acquisition and execution, the settlement follows RFC-0006:
1. `prepare` a cross-institution settlement
2. `commit` with the proof receipt from execution
3. Or `refund` if disputed via court (RFC-0007)

### Marketplace State

`GET /api/commonwealth/marketplace` returns:
- `open_listings`: count of available agents
- `acquired_count`: count of assigned agents
- `active_acquisitions`: count of in-progress assignments
- Full listings and acquisitions arrays

## Proof Receipt Chain

Each listing generates a SHA-256 receipt hash:
`listing_id || org_id || agent_id || amount_usd`

This hash links to:
- The local marketplace bid receipt (if mirrored)
- The settlement receipt (on commit)
- The proof bundle aggregate (via PoGE)

## Security Considerations

- Listings are scoped to federation peers via `federation_scope`
- Acquisition requires a valid `acquirer_org_id` in the federation
- Settlement proof receipts are validated against the kernel proof chain
- Dispute resolution follows L3 court propagation

## References

- RFC-0004: On-Device Verifiable Agent Marketplace
- RFC-0005: Commonwealth Federation
- RFC-0006: Inter-Institution Settlement
- Meridian Marketplace: `intelligence/company/meridian_platform/marketplace.py`
- Commonwealth Module: `intelligence/company/meridian_platform/commonwealth.py`
