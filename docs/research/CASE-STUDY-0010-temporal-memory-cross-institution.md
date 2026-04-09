# CASE-STUDY-0010: Cross-Institution Temporal Memory Verification

**RFC:** RFC-0009 (Temporal Memory Commonwealth Chain)  
**Date:** 2026-04-08  

## Scenario

Institution B disputes that Institution A's agent had access to critical information
at the time of execution. A needs to prove "who knew what when" with cryptographic
evidence.

## Steps

1. **A's memory graph:** Hash-chained events from agent execution
2. **Query anchor:** `GET /api/commonwealth/memory/anchor` returns verified state
3. **Verify chain:** `chain_valid: true`, `head_hash` matches expected
4. **Temporal query:** Filter events by agent_id and time range
5. **Proof nodes:** Minimal chain segment provided for independent verification
6. **B verifies:** Recomputes hashes from proof nodes, confirms match

## Observed Behavior

- Memory anchor returns `verified` status with head hash and chain validity
- Chain verification walks the full hash chain (O(n))
- Proof nodes include only the relevant segment for the query
- Anchor is embedded in the federated proof bundle for cross-reference

## Key Finding

The hash-chain approach provides tamper-evident temporal ordering. Any modification
to a past event breaks the chain, detectable by any verifier. The memory anchor
in the proof bundle binds temporal integrity to the broader PoGE verification —
a single proof bundle proves both execution correctness and temporal knowledge state.
