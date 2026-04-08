# RFC-0004: On-device Verifiable Agent Marketplace

Status: Draft (implementable)  
Owners: Loom + Kernel + Workspace maintainers  
Scope: bid/assign/settle/dispute lifecycle with treasury and court hooks

## Problem

Marketplace flows often stop at local module tests and do not propagate through treasury reserves, settlement splits, and dispute-driven court actions.

## Proposal

Wire marketplace lifecycle across runtime, treasury, court, API, and UI surfaces.

Lifecycle:

1. `submit_bid()`
2. `assign_bid()` -> reserve treasury funds
3. `settle_assignment()` -> verify proof+warrant -> deterministic split
4. `open_dispute()` -> freeze/review
5. `resolve_dispute()` -> release or refund

Data contract:

- `/api/status` -> `marketplace.{mode,open_bids,active_assignments,settled_count}`
- `GET /api/marketplace`
- `POST /api/marketplace/bids`
- `POST /api/marketplace/assign`
- `POST /api/marketplace/settle`
- `POST /api/marketplace/dispute`

## Acceptance Criteria

1. Deterministic split where `worker + royalty == total`.
2. Settlement lifecycle reflected in treasury reserve/commit/release events.
3. Dispute resolution can stay/refund/release and remains auditable.

## Rollback

Disable marketplace mutation endpoints and keep read-only snapshots active for debugging.

## References

- `intelligence/company/meridian_platform/marketplace.py`
- `intelligence/company/meridian_platform/workspace.py`
- `kernel/kernel/treasury.py`
