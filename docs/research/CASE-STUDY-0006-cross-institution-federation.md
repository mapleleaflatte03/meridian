# CASE-STUDY-0006: Cross-Institution Federation Bootstrap

**RFC:** RFC-0005 (Commonwealth Federation Layer on PoGE)  
**Date:** 2026-04-08  

## Scenario

Two research institutions (University A and Lab B) deploy Meridian independently
and need to federate for collaborative agent research.

## Steps

1. **Institution A** deploys Meridian with `install-full.sh`, producing org_a
2. **Lab B** deploys independently, producing org_b
3. **A links B:** `POST /api/commonwealth/federation/link` with B's host_id and org_id
4. **Verify:** `GET /api/commonwealth/federation` shows `peer_count: 1`, `enabled: true`
5. **Proof bundle:** `GET /api/commonwealth/proof-bundle` includes federation context

## Observed Behavior

- Federation link completes in < 50ms
- Fallback store works when full federation module is unavailable
- Proof bundle aggregates kernel proof + federation state + memory anchor
- No central authority required; each institution maintains sovereignty

## Key Finding

Federation is additive — linking a peer does not modify the existing governance
context. Each institution's court rules, treasury, and proof chain remain independent.
The federation layer provides a shared trust surface without governance coupling.
