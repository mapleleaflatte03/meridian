# RFC-0009: Temporal Memory Commonwealth Chain

**Status:** Implemented  
**Authors:** Meridian Research Contributors  
**Created:** 2026-04-08  
**Layer:** L5 — Temporal Memory Commonwealth Chain  

## Abstract

This RFC specifies the cross-institution temporal memory integrity protocol that
enables federated "who knew what when" verification. Each institution maintains a
hash-chained memory graph; the commonwealth chain anchors these graphs for
cross-institution temporal queries with cryptographic proof.

## Motivation

Individual Meridian institutions maintain temporal memory graphs (hash-chained event
sequences) that support `temporal_query_with_proof()` — proving which events were
known at a given time. Cross-institution workflows need this capability across
federation boundaries: institution A needs to verify that institution B's agent
had access to specific information at the time of execution.

## Protocol Design

### Memory Anchor

`GET /api/commonwealth/memory/anchor` returns the current temporal integrity state:

```json
{
  "anchor_status": "verified",
  "head_hash": "79cdd30a...",
  "index_version": 3,
  "chain_valid": true,
  "selected_events": 3,
  "proof_nodes_count": 3,
  "anchored_at": "2026-04-08T20:25:04Z",
  "protocol": "temporal_memory_commonwealth_chain_v1"
}
```

### Hash Chain Structure

Each memory node contains:
- `hash`: SHA-256 of `(prev_hash || agent_id || event_type || payload || timestamp)`
- `prev_hash`: pointer to the previous node (genesis node uses `"0"*64`)
- `agent_id`: the agent that produced this event
- `event_type`: classification of the event
- `payload`: event data
- `timestamp`: ISO 8601 timestamp

### Temporal Query with Proof

`temporal_query_with_proof(org_id, agent_id, before, after)` returns:
- `events`: filtered events matching the query
- `proof`: includes `head_hash`, `chain_valid`, `index_version`, and `proof_nodes`
  (the minimal set of nodes needed to verify the query result)

### Cross-Institution Verification

A federation peer can verify a temporal claim by:
1. Requesting the memory anchor from the target institution
2. Verifying the `chain_valid` flag and `head_hash`
3. Requesting specific temporal queries with proof
4. Independently recomputing hash chains from the proof nodes

### Anchor in Proof Bundle

The memory anchor is embedded in the federated proof bundle (RFC-0005):

```json
{
  "memory_anchor": {
    "head_hash": "79cdd30a...",
    "chain_valid": true,
    "index_version": 3
  }
}
```

This binds the temporal memory state to the PoGE proof aggregate.

### Degraded Mode

When the memory graph module is unavailable:
- `anchor_status` returns `"degraded"`
- `head_hash` is `null`
- `chain_valid` is `false`
- The error is recorded but the API remains functional

## Security Considerations

- Hash chains are append-only; tampering is detectable via chain validation
- Cross-institution queries are read-only; institutions cannot modify each other's
  memory graphs
- Proof nodes enable selective disclosure — institutions share only the minimal
  chain segment needed for verification
- Temporal ordering is based on wall-clock timestamps; clock skew between
  institutions should be bounded (recommended < 5s NTP sync)

## Future Work

- **Merkle inclusion proofs:** Replace linear chain verification with Merkle tree
  proofs for O(log n) verification
- **Cross-chain anchoring:** Anchor memory hashes to external blockchains for
  tamper-evident timestamping
- **Selective disclosure:** Zero-knowledge proofs for temporal queries that don't
  reveal event payloads

## References

- RFC-0005: Commonwealth Federation
- Meridian Memory Graph: `intelligence/company/meridian_platform/memory_graph.py`
- Commonwealth Module: `intelligence/company/meridian_platform/commonwealth.py`
