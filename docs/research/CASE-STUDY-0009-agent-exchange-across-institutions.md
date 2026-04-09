# CASE-STUDY-0009: Cross-Institution Agent Exchange

**RFC:** RFC-0008 (Verifiable Agent Exchange Protocol)  
**Date:** 2026-04-08  

## Scenario

Research lab A has developed an NLP analysis agent. University B wants to use it
for their dataset, acquiring it through the commonwealth marketplace.

## Steps

1. **A publishes:** Agent `agent_nlp_001` at $1.00, 10% royalty, scoped to [org_b]
2. **B discovers:** Listing appears in commonwealth marketplace
3. **B acquires:** `POST /api/commonwealth/marketplace/acquire` with listing_id
4. **Execution:** B runs the agent on their data
5. **Settlement:** B prepares and commits settlement with proof receipt
6. **Royalty split:** $0.90 to A (worker), $0.10 retained (platform)

## Observed Behavior

- Publish creates both a commonwealth listing and a local marketplace bid (mirror)
- Acquire assigns the listing and creates a reservation record
- Local bid assignment maintained for proof chain continuity
- Settlement receipt hash binds the full exchange lifecycle

## Key Finding

The dual-store approach (commonwealth listing + local marketplace mirror) ensures
that the local proof chain is maintained while enabling cross-institution visibility.
This preserves backward compatibility with single-institution marketplace operations.
