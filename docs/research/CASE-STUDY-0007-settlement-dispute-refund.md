# CASE-STUDY-0007: Cross-Institution Settlement with Dispute and Refund

**RFC:** RFC-0006 (Inter-Institution Treasury & Settlement Protocol)  
**Date:** 2026-04-08  

## Scenario

Institution A hires an agent from Institution B. The execution produces incorrect
results, leading to a dispute and court-ordered refund.

## Steps

1. **Prepare settlement:** A prepares $1.00 settlement for B's agent
2. **Commit:** A commits with proof receipt from execution
3. **Dispute:** B raises quality concern
4. **Court review:** Court issues decision ref `court_001`
5. **Refund:** Settlement refunded with court decision reference

## Observed Behavior

- Prepare creates receipt hash binding settlement params (SHA-256)
- Commit validates proof receipt against kernel chain
- Refund transitions status to `refunded` with court reference
- Treasury release recorded alongside refund
- Full lifecycle completes in < 150ms

## Key Finding

The settlement protocol cleanly separates financial state from governance decisions.
Court references provide non-repudiable justification for refunds without coupling
treasury operations to court module internals.
